import asyncio

import pytest
from mcp.types import CallToolResult, ListToolsResult, Tool

from trading_robinhood.connection import check_official_url, parse_callback
from trading_robinhood.guard import Catalog, GuardError, ReviewedMarketClient, sanitize

TOOL = Tool(
    name="get_equity_quotes",
    inputSchema={
        "type": "object",
        "properties": {"symbols": {"type": "array", "items": {"type": "string"}}},
        "required": ["symbols"],
        "additionalProperties": False,
    },
    outputSchema={
        "type": "object",
        "properties": {"price": {"type": "string"}},
        "required": ["price"],
        "additionalProperties": False,
    },
)


class Session:
    def __init__(self, tools=None, output=None):
        self.tools = tools if tools is not None else [TOOL]
        self.output = output if output is not None else {"price": "10"}
        self.calls = []

    async def list_tools(self, *, params=None):
        return ListToolsResult(tools=self.tools)

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        return CallToolResult(content=[], structuredContent=self.output)


def test_unapproved_tool_and_writes_never_reach_transport():
    async def scenario():
        session = Session()
        client = ReviewedMarketClient(session, {})
        with pytest.raises(GuardError, match="approved"):
            await client.call("get_equity_quotes", {"symbols": ["SYNTH"]})
        with pytest.raises(GuardError, match="allowlist"):
            await client.call("place_equity_order", {})
        assert session.calls == []

    asyncio.run(scenario())


def test_schema_drift_and_invalid_arguments_are_blocked():
    async def scenario():
        session = Session()
        catalog = await Catalog.capture(session)
        approved = {"get_equity_quotes": catalog.signature("get_equity_quotes")}
        client = ReviewedMarketClient(session, approved)
        with pytest.raises(GuardError, match="arguments"):
            await client.call("get_equity_quotes", {"symbols": "SYNTH"})
        session.tools = [TOOL.model_copy(update={"description": "new server contract"})]
        with pytest.raises(GuardError, match="changed"):
            await client.call("get_equity_quotes", {"symbols": ["SYNTH"]})
        assert session.calls == []

    asyncio.run(scenario())


def test_valid_call_validates_response_and_rejects_extra_fields():
    async def scenario():
        session = Session()
        catalog = await Catalog.capture(session)
        client = ReviewedMarketClient(
            session, {"get_equity_quotes": catalog.signature("get_equity_quotes")}
        )
        assert await client.call("get_equity_quotes", {"symbols": ["SYNTH"]}) == {"price": "10"}
        session.output = {"price": "10", "account_number": "not-for-model"}
        with pytest.raises(GuardError, match="response"):
            await client.call("get_equity_quotes", {"symbols": ["SYNTH"]})

    asyncio.run(scenario())


def test_catalog_detects_pagination_loop():
    class LoopingSession(Session):
        async def list_tools(self, *, params=None):
            return ListToolsResult(tools=[TOOL], nextCursor="same")

    with pytest.raises(GuardError):
        asyncio.run(Catalog.capture(LoopingSession()))


def test_sensitive_fields_are_removed_recursively():
    assert sanitize(
        {
            "price": "1",
            "account_number": "123",
            "nested": [{"access_token": "hidden", "symbol": "SYNTH"}],
        }
    ) == {"price": "1", "nested": [{"symbol": "SYNTH"}]}


@pytest.mark.parametrize(
    "url",
    [
        "http://agent.robinhood.com/mcp/trading",
        "https://agent.robinhood.com.attacker.invalid/mcp",
        "https://user@api.robinhood.com/oauth2/token/",
        "https://api.robinhood.com:444/oauth2/token/",
        "http://127.0.0.1:1234/private",
    ],
)
def test_oauth_cannot_send_tokens_to_unapproved_destination(url):
    with pytest.raises(ValueError):
        check_official_url(url)


def test_official_oauth_destinations_and_callback_state():
    check_official_url("https://agent.robinhood.com/mcp/trading")
    check_official_url("https://api.robinhood.com/oauth2/token/")
    check_official_url("https://robinhood.com/oauth?state=test")
    result = parse_callback("/callback?code=test-code&state=expected", "expected")
    assert result.code == "test-code"
    with pytest.raises(ValueError):
        parse_callback("/callback?code=test-code&state=wrong", "expected")
    with pytest.raises(ValueError):
        parse_callback("/callback?code=one&code=two&state=expected", "expected")
