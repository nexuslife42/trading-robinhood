"""Reviewed public-market tools only. No account, preview, or trading passthrough."""

import re
from typing import Any, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from mcp.types import (
    CallToolResult,
    InputRequiredResult,
    ListToolsResult,
    PaginatedRequestParams,
    Result,
)

from .models import digest

MARKET_TOOLS = frozenset(
    {
        "search",
        "get_equity_quotes",
        "get_equity_historicals",
        "get_equity_fundamentals",
        "get_financials",
        "get_equity_tradability",
        "get_earnings_results",
        "get_earnings_calendar",
        "get_indexes",
        "get_index_quotes",
        "get_option_historicals",
        "get_option_chains",
        "get_option_instruments",
        "get_option_quotes",
        "get_currency_pairs",
        "get_crypto_quotes",
    }
)
SENSITIVE_KEY = re.compile(
    r"account|token|secret|password|authorization|customer|email|phone|address", re.I
)


class GuardError(ValueError):
    pass


class ToolSession(Protocol):
    async def list_tools(
        self, *, params: PaginatedRequestParams | None = None
    ) -> ListToolsResult: ...
    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> CallToolResult | InputRequiredResult | Result: ...


def sanitize(value: Any, depth: int = 0) -> Any:
    if depth > 20:
        raise GuardError("Response nesting exceeds limit")
    if isinstance(value, dict):
        return {
            key: sanitize(item, depth + 1)
            for key, item in value.items()
            if not SENSITIVE_KEY.search(key)
        }
    if isinstance(value, list):
        if len(value) > 1000:
            raise GuardError("Response array exceeds limit")
        return [sanitize(item, depth + 1) for item in value]
    return value


def check_schema(schema: dict[str, Any]) -> None:
    def visit(value: Any) -> None:
        if isinstance(value, dict):
            reference = value.get("$ref", "")
            if reference and not reference.startswith("#"):
                raise GuardError("Remote schema references are forbidden")
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(schema)
    Draft202012Validator.check_schema(schema)


class Catalog:
    def __init__(self, tools: dict[str, dict[str, Any]]):
        self.tools = tools

    @classmethod
    async def capture(cls, session: ToolSession) -> "Catalog":
        tools: dict[str, dict[str, Any]] = {}
        cursor = None
        seen: set[str] = set()
        for _ in range(100):
            page = await session.list_tools(params=PaginatedRequestParams(cursor=cursor))
            for tool in page.tools:
                if tool.name in tools or len(tools) >= 1000:
                    raise GuardError("Duplicate or excessive tool catalog")
                tools[tool.name] = tool.model_dump(mode="json", by_alias=True)
            cursor = page.next_cursor
            if not cursor:
                return cls(tools)
            if cursor in seen:
                raise GuardError("Catalog pagination loop")
            seen.add(cursor)
        raise GuardError("Catalog pagination exceeds limit")

    def signature(self, name: str) -> str:
        if name not in self.tools:
            raise GuardError("Tool disappeared")
        return digest(self.tools[name])

    def document(self) -> dict[str, Any]:
        return {
            "tools": self.tools,
            "catalog_digest": digest(self.tools),
            "signatures": {name: self.signature(name) for name in self.tools},
            "trusted_as_instructions": False,
        }


class ReviewedMarketClient:
    def __init__(self, session: ToolSession, approved: dict[str, str]):
        self.session, self.approved = session, approved

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in MARKET_TOOLS:
            raise GuardError("Tool is outside the public-market allowlist")
        if name not in self.approved:
            raise GuardError("Tool contract has not been approved")
        catalog = await Catalog.capture(self.session)
        if catalog.signature(name) != self.approved[name]:
            raise GuardError("Tool contract changed; new review required")
        tool = catalog.tools[name]
        schema = tool.get("outputSchema")
        if not schema:
            raise GuardError("A reviewed structured response schema is required")
        try:
            check_schema(tool["inputSchema"])
            check_schema(schema)
            Draft202012Validator(tool["inputSchema"]).validate(arguments)
        except (SchemaError, ValidationError) as exc:
            raise GuardError("Tool arguments or schema failed validation") from exc
        result = await self.session.call_tool(name, arguments)
        if (
            not isinstance(result, CallToolResult)
            or result.is_error
            or result.structured_content is None
        ):
            raise GuardError("Tool response is an error or lacks structured data")
        try:
            Draft202012Validator(schema).validate(result.structured_content)
        except ValidationError as exc:
            raise GuardError("Tool response failed validation") from exc
        return sanitize(result.structured_content)
