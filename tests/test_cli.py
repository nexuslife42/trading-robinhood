import json
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal

import pytest
from mcp.shared.auth import OAuthToken
from test_policy import NOW, order, policy, quote

from trading_robinhood import cli, connection
from trading_robinhood.execution import Executor
from trading_robinhood.paper import PaperBroker
from trading_robinhood.state import ExecutionError, State


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "trading_robinhood", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_doctor_reports_disabled_live_without_broker_login():
    result = run_cli("doctor")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["live_submission"] == "disabled: uncertified broker contract"


def test_live_command_cannot_be_enabled_with_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("RH_LIVE_ENABLED", "true")
    result = run_cli("live", "--state", str(tmp_path / "live.db"))
    assert result.returncode != 0
    assert "disabled" in result.stderr
    assert not (tmp_path / "live.db").exists()


def test_approval_refuses_noninteractive_input(tmp_path):
    result = run_cli(
        "approve-execute",
        "11111111-1111-4111-8111-111111111111",
        "--state",
        str(tmp_path / "paper.db"),
    )
    assert result.returncode != 0
    assert "interactive" in result.stderr


def test_example_replay_runs_from_cli():
    result = run_cli("replay", "examples/synthetic-replay.json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["cash"] == "979"


def test_status_and_backup_preserve_approval_and_halt_state(tmp_path):
    path = tmp_path / "paper.db"
    state = State(path)
    broker = PaperBroker(state, account="paper", cash=Decimal("1000"))
    broker.set_quote(quote())
    executor = Executor(state, broker, policy(), release="test")
    key = executor.propose(order(), NOW)
    executor.approve(key, NOW)
    before = state.get_order(key)
    for args in [("status",), ("history", key), ("backup", str(tmp_path / "backup.db"))]:
        result = run_cli(*args, "--state", str(path))
        assert result.returncode == 0, result.stderr
        assert state.get_order(key) == before
        assert not state.halted
    state.close()


@pytest.mark.parametrize("submitted", [False, True])
def test_paper_tick_updates_only_submitted_orders_and_preserves_halt(tmp_path, submitted):
    path = tmp_path / "paper.db"
    state = State(path)
    broker = PaperBroker(state, account="paper", cash=Decimal("1000"), fee=Decimal("1"))
    broker.set_quote(quote())
    executor = Executor(state, broker, policy(), release="test")
    key = executor.propose(order(), NOW)
    if submitted:
        executor.approve(key, NOW)
        executor.execute(key, NOW)
    executor.halt("test", NOW)
    tick = tmp_path / "tick.json"
    for second, expected_cash, expected_status in [(1, "989", "partial"), (2, "979", "filled")]:
        tick.write_text(
            json.dumps(
                {
                    "at": (NOW + timedelta(seconds=second)).isoformat(),
                    "instrument": "SYNTH",
                    "bid": "9",
                    "ask": "10",
                    "liquidity": "1",
                }
            )
        )
        result = run_cli("paper-tick", str(tick), "--state", str(path))
        assert result.returncode == 0, result.stderr
        output = json.loads(result.stdout)
        assert output["mode"] == "paper"
        assert state.halted
        row = state.get_order(key)
        if submitted:
            assert row["status"] == expected_status
            assert row["filled_quantity"] == str(second)
            assert output["portfolio"]["buying_power"] == expected_cash
            assert output["portfolio"]["positions"] == {"SYNTH": str(second)}
        else:
            assert row["status"] == "proposed"
            assert row["approval"] is None
            assert output["portfolio"]["buying_power"] == "1000"
            assert output["portfolio"]["positions"] == {}
    if submitted:
        assert [event["kind"] for event in state.events(key)][-2:] == ["partial", "filled"]
    state.close()


@pytest.mark.parametrize("liquidity", ["-1", "NaN", 1.5])
def test_paper_tick_rejects_invalid_liquidity_without_loading_quote(tmp_path, liquidity):
    path = tmp_path / "paper.db"
    tick = tmp_path / "tick.json"
    tick.write_text(
        json.dumps(
            {
                "at": NOW.isoformat(),
                "instrument": "SYNTH",
                "bid": "9",
                "ask": "10",
                "liquidity": liquidity,
            }
        )
    )
    result = run_cli("paper-tick", str(tick), "--state", str(path))
    assert result.returncode == 1
    state = State(path)
    assert state.connection.execute("SELECT COUNT(*) FROM paper_quotes").fetchone()[0] == 0
    state.close()


def test_paper_tick_requires_explicit_ledger(tmp_path):
    result = run_cli("paper-tick", str(tmp_path / "tick.json"))
    assert result.returncode == 2
    assert "--state" in result.stderr


def test_paper_tick_keeps_ledger_locked_until_portfolio_is_captured(tmp_path, monkeypatch):
    path = tmp_path / "paper.db"
    tick = tmp_path / "tick.json"
    tick.write_text(
        json.dumps(
            {
                "at": NOW.isoformat(),
                "instrument": "SYNTH",
                "bid": "9",
                "ask": "10",
                "liquidity": "1",
            }
        )
    )
    snapshot = PaperBroker.snapshot

    def competing_snapshot(broker, now):
        competitor = State(path)
        try:
            with pytest.raises(ExecutionError, match="busy"):
                with competitor.lock():
                    pass
        finally:
            competitor.close()
        return snapshot(broker, now)

    monkeypatch.setattr(PaperBroker, "snapshot", competing_snapshot)
    assert cli.main(["paper-tick", str(tick), "--state", str(path)]) == 0


@pytest.mark.parametrize("failure", ["malformed_token", "transport"])
def test_discovery_errors_never_print_credentials(tmp_path, monkeypatch, capsys, failure):
    async def fail_discovery():
        if failure == "malformed_token":
            return OAuthToken.model_validate({"refresh_token": "SYNTHETIC-PRIVATE-VALUE"})
        raise RuntimeError("transport response SYNTHETIC-PRIVATE-VALUE")

    monkeypatch.setattr(connection, "discover", fail_discovery)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    destination = tmp_path / "catalog.json"
    assert cli.main(["broker-discover", "--connect", "--output", str(destination)]) == 1
    captured = capsys.readouterr()
    assert "SYNTHETIC-PRIVATE-VALUE" not in captured.out + captured.err
    assert "Broker discovery failed" in captured.err
    assert not destination.exists()
