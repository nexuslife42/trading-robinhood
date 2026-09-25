"""Explicit operator-only OAuth discovery using the official MCP SDK and macOS Keychain."""

import asyncio
import hmac
import json
import sys
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
from keyring.backend import KeyringBackend
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import (
    AuthorizationCodeResult,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)
from pydantic import AnyUrl

ENDPOINT = "https://agent.robinhood.com/mcp/trading"
SERVICE = "trading-robinhood:official-mcp:v1"


def check_official_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.fragment
    ):
        raise ValueError("Unapproved authentication destination")
    allowed = {
        "agent.robinhood.com": ("/mcp/trading", "/.well-known/", "/oauth/trading/register"),
        "api.robinhood.com": ("/oauth2/token/",),
        "robinhood.com": ("/oauth",),
    }
    paths = allowed.get(parsed.hostname or "", ())
    if not any(
        parsed.path == path or (path.endswith("/") and parsed.path.startswith(path))
        for path in paths
    ):
        raise ValueError("Unapproved authentication destination")


def parse_callback(path: str, expected_state: str) -> AuthorizationCodeResult:
    parsed = urlsplit(path)
    values = parse_qs(parsed.query)
    if parsed.path != "/callback" or "error" in values:
        raise ValueError("Invalid OAuth callback")
    if not expected_state or len(values.get("code", [])) != 1 or len(values.get("state", [])) != 1:
        raise ValueError("Invalid OAuth callback parameters")
    if not hmac.compare_digest(values["state"][0], expected_state):
        raise ValueError("OAuth state mismatch")
    if len(values.get("iss", [])) > 1:
        raise ValueError("Duplicate OAuth issuer")
    return AuthorizationCodeResult(
        code=values["code"][0], state=values["state"][0], iss=values.get("iss", [None])[0]
    )


class KeychainStore:
    backend: KeyringBackend

    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise ValueError("Broker credentials require macOS Keychain; no file fallback")
        from keyring.backends.macOS import Keyring

        create_backend: Callable[[], KeyringBackend] = Keyring
        self.backend = create_backend()

    async def get_tokens(self) -> OAuthToken | None:
        value = self.backend.get_password(SERVICE, "tokens")
        return OAuthToken.model_validate_json(value) if value else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.backend.set_password(SERVICE, "tokens", tokens.model_dump_json())

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        value = self.backend.get_password(SERVICE, "client")
        return OAuthClientInformationFull.model_validate_json(value) if value else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.backend.set_password(SERVICE, "client", client_info.model_dump_json())

    def clear(self) -> None:
        for item in ("tokens", "client"):
            if self.backend.get_password(SERVICE, item) is not None:
                self.backend.delete_password(SERVICE, item)


class OAuthCallback:
    def __init__(self) -> None:
        self.state = ""
        self.result: AuthorizationCodeResult | None = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                try:
                    owner.result = parse_callback(self.path, owner.state)
                except ValueError:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Invalid authentication callback.")
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Authentication received. Return to your terminal.")

            def log_message(self, format: str, *args: Any) -> None:
                # Callback URLs contain authorization codes; never log them.
                return

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.server.timeout = 1

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/callback"

    async def redirect(self, url: str) -> None:
        check_official_url(url)
        values = parse_qs(urlsplit(url).query)
        states = values.get("state", [])
        if len(states) != 1:
            raise ValueError("OAuth authorization state missing")
        self.state = states[0]
        print("Open this official Robinhood login URL in your browser:\n" + url, file=sys.stderr)

    async def receive(self) -> AuthorizationCodeResult:
        deadline = time.monotonic() + 180
        while self.result is None and time.monotonic() < deadline:
            await asyncio.to_thread(self.server.handle_request)
        if self.result is None:
            raise ValueError("OAuth callback timed out")
        return self.result

    def close(self) -> None:
        self.server.server_close()


@asynccontextmanager
async def connected_session() -> AsyncIterator[ClientSession]:
    callback = OAuthCallback()
    try:

        async def validate_request(request: httpx2.Request) -> None:
            check_official_url(str(request.url))

        async def validate_resource(url: str, parent: str | None) -> None:
            check_official_url(url)

        auth = OAuthClientProvider(
            ENDPOINT,
            OAuthClientMetadata(
                redirect_uris=[AnyUrl(callback.url)],
                token_endpoint_auth_method="none",  # noqa: S106 -- public OAuth client, no secret
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
                client_name="Personal Trading Foundation",
            ),
            KeychainStore(),
            redirect_handler=callback.redirect,
            callback_handler=callback.receive,
            validate_resource_url=validate_resource,
        )
        async with httpx2.AsyncClient(
            auth=auth,
            timeout=30,
            follow_redirects=False,
            trust_env=False,
            event_hooks={"request": [validate_request]},
        ) as http:
            async with streamable_http_client(ENDPOINT, http_client=http) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=30) as session:
                    await session.initialize()
                    yield session
    finally:
        callback.close()


async def discover() -> dict[str, Any]:
    from .guard import Catalog

    async with connected_session() as session:
        catalog = await Catalog.capture(session)
        document = {"endpoint": ENDPOINT, **catalog.document()}
        if len(json.dumps(document)) > 2_000_000:
            raise ValueError("Catalog exceeds size limit")
        return document
