import json
import subprocess
import sys
from decimal import Decimal

import pytest
from mcp.shared.auth import OAuthToken
from test_policy import NOW, order, policy, quote

from trading_robinhood import cli, connection
from trading_robinhood.execution import Executor
from trading_robinhood.paper import PaperBroker
from trading_robinhood.state import State


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
