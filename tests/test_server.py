import asyncio
import sys

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from trading_robinhood.models import Policy
from trading_robinhood.server import create_server


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
