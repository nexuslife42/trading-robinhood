import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters
from test_cli import run_cli

from trading_robinhood.cli import policy_from
from trading_robinhood.execution import Executor
from trading_robinhood.models import Policy, Quote
from trading_robinhood.paper import PaperBroker
from trading_robinhood.server import create_server
from trading_robinhood.state import State


def test_agent_surface_cannot_approve_submit_or_reach_robinhood(tmp_path):
    async def scenario():
        server = create_server(tmp_path / "paper.db", Policy())
        async with Client(server) as client:
            tools = (await client.list_tools()).tools
            assert {tool.name for tool in tools} == {
                "foundation_status",
                "paper_portfolio",
                "propose_paper_order",
                "paper_order_status",
                "halt_paper",
            }
            result = await client.call_tool("foundation_status", {})
            assert result.structured_content["mode"] == "paper"
            assert result.structured_content["live_available"] is False
            result = await client.call_tool("place_equity_order", {})
            assert result.is_error

    asyncio.run(scenario())


def test_cli_stdio_server_reports_paper_only(tmp_path):
    async def scenario():
        command = StdioServerParameters(
            command=sys.executable,
            args=["-m", "trading_robinhood", "serve", "--state", str(tmp_path / "stdio.db")],
        )
        async with Client(command, read_timeout_seconds=10) as client:
            result = await client.call_tool("foundation_status", {})
            assert result.structured_content["live_available"] is False
            assert result.structured_content["mode"] == "paper"

    asyncio.run(scenario())


def test_mcp_proposal_and_cli_ticks_share_persistent_fills(tmp_path):
    async def scenario():
        path = tmp_path / "paper.db"
        now = datetime.now(UTC)
        state = State(path)
        broker = PaperBroker(state, account="paper", cash=Decimal("1000"), fee=Decimal("1"))
        broker.set_quote(Quote(instrument="SYNTH", bid="9", ask="10", observed_at=now))
        command = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "trading_robinhood",
                "serve",
                "--state",
                str(path),
                "--policy",
                "config/paper.toml",
            ],
        )
        key = "33333333-3333-4333-8333-333333333333"
        async with Client(command, read_timeout_seconds=10) as client:
            proposal = await client.call_tool(
                "propose_paper_order",
                {
                    "intent": {
                        "request_id": key,
                        "account": "paper",
                        "instrument": "SYNTH",
                        "side": "buy",
                        "quantity": "2",
                        "limit_price": "10",
                    }
                },
            )
            assert not proposal.is_error
            # Scripted approval exists only in this isolated test, never in the MCP surface.
            executor = Executor(
                state, broker, policy_from(Path("config/paper.toml")), release="development-paper"
            )
            executor.approve(key, datetime.now(UTC))
            executor.execute(key, datetime.now(UTC))
            for second, status, quantity, cash in [
                (1, "partial", "1", "989"),
                (2, "filled", "2", "979"),
            ]:
                tick = tmp_path / f"tick-{second}.json"
                tick.write_text(
                    json.dumps(
                        {
                            "at": (datetime.now(UTC) + timedelta(seconds=second)).isoformat(),
                            "instrument": "SYNTH",
                            "bid": "9",
                            "ask": "10",
                            "liquidity": "1",
                        }
                    )
                )
                result = run_cli("paper-tick", str(tick), "--state", str(path))
                assert result.returncode == 0, result.stderr
                order = await client.call_tool("paper_order_status", {"request_id": key})
                assert order.structured_content["status"] == status
                assert order.structured_content["filled_quantity"] == quantity
                portfolio = await client.call_tool("paper_portfolio", {})
                assert portfolio.structured_content["buying_power"] == cash
        state.close()
        async with Client(command, read_timeout_seconds=10) as client:
            order = await client.call_tool("paper_order_status", {"request_id": key})
            portfolio = await client.call_tool("paper_portfolio", {})
            assert order.structured_content["status"] == "filled"
            assert portfolio.structured_content["positions"] == {"SYNTH": "2"}
            assert portfolio.structured_content["buying_power"] == "979"

    asyncio.run(scenario())
