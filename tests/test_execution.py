import sqlite3
from datetime import timedelta
from decimal import Decimal

import pytest
from test_policy import NOW, order, policy, quote

from trading_robinhood.execution import ExecutionError, Executor
from trading_robinhood.models import OrderResult
from trading_robinhood.paper import PaperBroker
from trading_robinhood.state import State


@pytest.fixture
def rig(tmp_path):
    state = State(tmp_path / "state.sqlite3")
    broker = PaperBroker(state, account="paper", cash=Decimal("1000"))
    broker.set_quote(quote())
    executor = Executor(state, broker, policy(), release="test-release")
    try:
        yield state, broker, executor
    finally:
        state.close()


def prepare(executor, intent=None):
    intent = intent or order()
    key = executor.propose(intent, NOW)
    executor.approve(key, NOW)
    return key


def test_requires_approval_and_consumes_it_once(rig):
    state, broker, executor = rig
    key = executor.propose(order(), NOW)
    with pytest.raises(ExecutionError, match="approval"):
        executor.execute(key, NOW)
    executor.approve(key, NOW)
    result = executor.execute(key, NOW)
    assert result.status == "open"
    with pytest.raises(ExecutionError):
        executor.execute(key, NOW)
    assert len(broker.orders()) == 1
    assert state.get_order(key)["status"] == "open"
    assert [event["kind"] for event in state.events(key)] == [
        "proposed",
        "approved",
        "submitting",
        "open",
    ]


@pytest.mark.parametrize("change", ["policy", "release", "quote", "expiry"])
def test_approval_binding_rejects_changed_context(rig, change):
    state, broker, executor = rig
    key = prepare(executor)
    now = NOW
    if change == "policy":
        executor = Executor(state, broker, policy(version="2"), release="test-release")
    if change == "release":
        executor = Executor(state, broker, policy(), release="different-release")
    if change == "quote":
        broker.set_quote(quote(ask="11"))
    if change == "expiry":
        now += timedelta(seconds=61)
    with pytest.raises(ExecutionError):
        executor.execute(key, now)
    assert broker.orders() == []


def test_same_request_id_with_different_payload_rejected(rig):
    _, _, executor = rig
    executor.propose(order(), NOW)
    with pytest.raises(ExecutionError, match="duplicate"):
        executor.propose(order(quantity="3"), NOW)


def test_pending_commitments_block_second_order(rig):
    state, broker, _ = rig
    executor = Executor(state, broker, policy(max_daily_value="30"), release="test-release")
    first = prepare(executor)
    second = prepare(executor, order(request_id="22222222-2222-4222-8222-222222222222"))
    executor.execute(first, NOW)
    with pytest.raises(ExecutionError, match="daily_value_limit"):
        executor.execute(second, NOW)
    assert len(broker.orders()) == 1


def test_timeout_after_broker_acceptance_halts_and_reconciles_without_retry(rig):
    state, broker, executor = rig
    key = prepare(executor)
    original = broker.submit

    def lose_response(intent, now):
        original(intent, now)
        raise TimeoutError("network lost")

    broker.submit = lose_response
    with pytest.raises(ExecutionError, match="unknown"):
        executor.execute(key, NOW)
    assert state.halted
    assert state.get_order(key)["status"] == "unknown"
    assert executor.reconcile(key, NOW).status == "open"
    assert state.halted  # reconciliation never silently resumes trading
    assert len(broker.orders()) == 1
    with pytest.raises(ExecutionError):
        executor.execute(key, NOW)


def test_crash_after_send_is_recovered_on_restart(rig):
    state, broker, executor = rig
    key = prepare(executor)
    original = broker.submit

    def crash(intent, now):
        original(intent, now)
        raise SystemExit("process crash")

    broker.submit = crash
    with pytest.raises(SystemExit):
        executor.execute(key, NOW)
    assert state.get_order(key)["status"] == "submitting"
    restarted = Executor(state, broker, policy(), release="test-release")
    assert state.halted
    assert restarted.reconcile(key, NOW).status == "open"
    assert len(broker.orders()) == 1


def test_storage_failure_prevents_submission(rig):
    state, broker, executor = rig
    key = prepare(executor)
    state.connection.execute("PRAGMA query_only = ON")
    with pytest.raises(sqlite3.OperationalError):
        executor.execute(key, NOW)
    assert broker.orders() == []


def test_halt_persists_and_cancellation_is_allowed_while_halted(rig):
    state, broker, executor = rig
    key = prepare(executor)
    executor.execute(key, NOW)
    executor.halt("operator", NOW)
    with pytest.raises(ExecutionError, match="halted"):
        executor.propose(order(request_id="22222222-2222-4222-8222-222222222222"), NOW)
    assert executor.cancel(key, NOW).status == "canceled"
    reopened = State(state.path)
    assert reopened.halted
    reopened.close()
    assert broker.snapshot(NOW).buying_power == Decimal("1000")


def test_unknown_reconciliation_does_not_free_reservations(rig):
    state, broker, executor = rig
    key = prepare(executor)

    def disconnected(intent, now):
        raise TimeoutError

    broker.submit = disconnected
    with pytest.raises(ExecutionError):
        executor.execute(key, NOW)
    result = executor.reconcile(key, NOW)
    assert result.status == "unknown"
    assert state.usage("paper", NOW, Decimal("1")).reserved_cash == Decimal("21")
    with pytest.raises(ExecutionError, match="unresolved"):
        executor.resume(NOW)


def test_invalid_broker_result_halts_instead_of_freeing_reserves(rig):
    state, broker, executor = rig
    key = prepare(executor)
    broker.submit = lambda intent, now: OrderResult(
        broker_id="bad", status="filled", filled_quantity="999"
    )
    with pytest.raises(ExecutionError):
        executor.execute(key, NOW)
    assert state.halted
    assert state.get_order(key)["status"] == "unknown"


def test_local_lock_prevents_two_executors_from_dispatching(rig):
    state, _, executor = rig
    key = prepare(executor)
    with state.lock():
        with pytest.raises(ExecutionError, match="busy"):
            executor.execute(key, NOW)


def test_filled_order_wins_a_cancellation_race(rig):
    state, broker, executor = rig
    key = prepare(executor)
    executor.execute(key, NOW)
    broker.advance(quote(observed_at=NOW + timedelta(seconds=1)), Decimal("2"))
    result = executor.cancel(key, NOW + timedelta(seconds=2))
    assert result.status == "filled"
    assert state.get_order(key)["filled_quantity"] == "2"
    assert broker.snapshot(NOW).positions["SYNTH"] == Decimal("2")


def test_restart_invalidates_unused_approvals(rig):
    state, broker, executor = rig
    key = prepare(executor)
    restarted = Executor(state, broker, policy(), release="test-release")
    with pytest.raises(ExecutionError, match="approval"):
        restarted.execute(key, NOW)
    assert broker.orders() == []


@pytest.mark.parametrize("operation", ["submit", "cancel"])
def test_failed_uncertainty_write_blocks_existing_executor_until_manual_resume(rig, operation):
    state, broker, executor = rig
    first = prepare(executor)
    second = prepare(executor, order(request_id="22222222-2222-4222-8222-222222222222"))
    if operation == "cancel":
        executor.execute(first, NOW)
    original = getattr(broker, operation)

    def accept_then_break_persistence(*args):
        result = original(*args)
        state.connection.execute(
            "CREATE TEMP TRIGGER fail_event BEFORE INSERT ON events "
            "BEGIN SELECT RAISE(FAIL, 'disk write unavailable'); END"
        )
        return result

    setattr(broker, operation, accept_then_break_persistence)
    with pytest.raises((sqlite3.Error, ExecutionError)):
        if operation == "submit":
            executor.execute(first, NOW)
        else:
            executor.cancel(first, NOW)
    state.connection.execute("DROP TRIGGER fail_event")
    setattr(broker, operation, original)
    assert state.get_order(first)["status"] in ("submitting", "cancel_pending")
    assert state.halted  # The durable unresolved status blocks every process.
    with pytest.raises(ExecutionError, match="halted|unresolved"):
        executor.execute(second, NOW)
    executor.reconcile(first, NOW)
    assert state.halted  # Reconciliation must not erase the halt across a later restart.
    with pytest.raises(ExecutionError, match="halted|unresolved"):
        executor.execute(second, NOW)
    executor.resume(NOW)
    executor.execute(second, NOW)
    assert len(broker.orders()) == 2
