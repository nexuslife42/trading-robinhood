from datetime import timedelta
from decimal import Decimal

import pytest
from test_policy import NOW, order, quote

from trading_robinhood.paper import PaperBroker
from trading_robinhood.state import State


@pytest.fixture
def state(tmp_path):
    ledger = State(tmp_path / "paper.db")
    try:
        yield ledger
    finally:
        ledger.close()


def test_partial_fill_fee_and_settlement_accounting(state):
    broker = PaperBroker(
        state,
        account="paper",
        cash=Decimal("100"),
        fee=Decimal("1"),
        slippage_bps=Decimal("0"),
    )
    broker.set_quote(quote())
    broker.submit(order(), NOW)
    result = broker.advance(quote(observed_at=NOW + timedelta(seconds=1)), Decimal("1"))[0]
    assert result.status == "partial"
    assert result.filled_quantity == Decimal("1")
    assert broker.snapshot(NOW).buying_power == Decimal("89")
    broker.advance(quote(observed_at=NOW + timedelta(seconds=2)), Decimal("1"))
    assert broker.snapshot(NOW).buying_power == Decimal("79")
    assert broker.snapshot(NOW).positions == {"SYNTH": Decimal("2")}
    sell = order(
        side="sell",
        quantity="1",
        limit_price="9",
        request_id="22222222-2222-4222-8222-222222222222",
    )
    broker.submit(sell, NOW + timedelta(seconds=3))
    broker.advance(quote(observed_at=NOW + timedelta(seconds=4)), Decimal("1"))
    assert broker.snapshot(NOW).buying_power == Decimal("78")  # fee now, proceeds unsettled
    assert broker.snapshot(NOW + timedelta(days=2)).buying_power == Decimal("87")


def test_no_fill_on_same_tick_or_before_limit(state):
    broker = PaperBroker(state, account="paper", cash=Decimal("100"))
    broker.set_quote(quote())
    broker.submit(order(limit_price="9"), NOW)
    assert broker.advance(quote(), Decimal("100")) == []
    assert broker.advance(quote(observed_at=NOW + timedelta(seconds=1)), Decimal("100")) == []
    assert broker.snapshot(NOW).buying_power == Decimal("100")


def test_slippage_cannot_cross_limit_and_cancel_does_not_reverse_fill(state):
    broker = PaperBroker(
        state,
        account="paper",
        cash=Decimal("100"),
        slippage_bps=Decimal("100"),
    )
    broker.set_quote(quote())
    broker.submit(order(limit_price="11"), NOW)
    broker.advance(quote(observed_at=NOW + timedelta(seconds=1)), Decimal("1"))
    canceled = broker.cancel(str(order().request_id), NOW + timedelta(seconds=2))
    assert canceled.status == "canceled"
    assert canceled.filled_quantity == Decimal("1")
    assert broker.snapshot(NOW).buying_power == Decimal("89.90")
    assert broker.advance(quote(observed_at=NOW + timedelta(seconds=3)), Decimal("10")) == []


def test_day_order_expires_and_future_quotes_are_not_visible(state):
    broker = PaperBroker(state, account="paper", cash=Decimal("100"))
    broker.set_quote(quote())
    broker.submit(order(), NOW)
    broker.advance(quote(observed_at=NOW + timedelta(days=1)), Decimal("10"))
    assert broker.lookup(str(order().request_id), NOW).status == "canceled"
    with pytest.raises(ValueError, match="future"):
        broker.quote("SYNTH", NOW)


def test_paper_state_survives_restart_and_initial_cash_is_not_reset(state):
    broker = PaperBroker(state, account="paper", cash=Decimal("100"))
    broker.set_quote(quote())
    broker.submit(order(), NOW)
    broker.advance(quote(observed_at=NOW + timedelta(seconds=1)), Decimal("2"))
    restarted = PaperBroker(State(state.path), account="paper", cash=Decimal("99999"))
    assert restarted.snapshot(NOW).buying_power == Decimal("80")
    assert restarted.snapshot(NOW).positions["SYNTH"] == Decimal("2")
    restarted.state.close()


def test_repeated_tick_cannot_supply_more_liquidity_after_restart(state):
    broker = PaperBroker(state, account="paper", cash=Decimal("100"), fee=Decimal("1"))
    broker.set_quote(quote())
    broker.submit(order(), NOW)
    tick = quote(observed_at=NOW + timedelta(seconds=2))
    broker.advance(tick, Decimal("1"))
    restarted = PaperBroker(State(state.path), account="paper", cash=Decimal("100"))
    try:
        for at in [tick.observed_at, NOW + timedelta(seconds=1)]:
            with pytest.raises(ValueError, match="Tick time"):
                restarted.advance(quote(observed_at=at), Decimal("1"))
        assert restarted.lookup(str(order().request_id), NOW).filled_quantity == Decimal("1")
        assert restarted.snapshot(NOW).buying_power == Decimal("89")
    finally:
        restarted.state.close()


def test_failed_tick_rolls_back_quote_fills_and_tick_timestamp(state, monkeypatch):
    broker = PaperBroker(state, account="paper", cash=Decimal("100"))
    broker.set_quote(quote())
    broker.submit(order(), NOW)
    tick = quote(observed_at=NOW + timedelta(seconds=1))

    def fail_save(*args):
        raise OSError("simulated storage failure")

    with monkeypatch.context() as patch:
        patch.setattr(broker, "_save", fail_save)
        with pytest.raises(OSError):
            broker.advance(tick, Decimal("1"))
    assert broker.quote("SYNTH", NOW) == quote()
    assert broker.lookup(str(order().request_id), NOW).filled_quantity == 0
    assert broker.advance(tick, Decimal("1"))[0].filled_quantity == 1
