# Robinhood connection assessment

Verified public documentation and unauthenticated HTTP behavior on 2026-09-24. Robinhood hosts `https://agent.robinhood.com/mcp/trading`. MCP initialization returned 401 without a token. Public OAuth metadata advertises `internal`, authorization code/refresh flows, and S256 PKCE; it does not establish a separate read-only scope.

The official OAuth destinations observed were `https://robinhood.com/oauth`, `https://agent.robinhood.com/oauth/trading/register`, and `https://api.robinhood.com/oauth2/token/`. The implementation rejects other destinations rather than following arbitrary metadata URLs.

## Capability boundaries

| Group | Documented behavior | This foundation |
|---|---|---|
| Accounts and portfolio | Balances, positions, realized P&L and history | Disabled pending account filtering contracts |
| Watchlists and scans | Queries plus create/update/follow/remove operations | Disabled |
| Market data | Quotes, historicals, fundamentals, financials, earnings, indexes, options and crypto data | Only reviewed, schema-pinned public-market calls |
| Equity/options orders | Review, place, cancel and history | All broker calls disabled |
| Crypto orders | Preview, place, cancel and history | All broker calls disabled |

Robinhood documents long equities, options, and crypto support with account/region restrictions. Reads can cover other Robinhood accounts even though trading is confined to an Agentic account. Margin borrowing is not enabled. Agentic crypto cannot transfer, stake, or lend; New York is among restricted states. Do not infer residence from the computer's timezone.

No official paper-account endpoint, comprehensive rate limit, or safe order retry contract was established. The local simulator is separate from Robinhood. Broker preview tools do not prove a full paper execution environment exists.

Sources: [overview](https://robinhood.com/us/en/support/articles/agentic-trading-overview/), [tool catalog](https://robinhood.com/us/en/support/articles/trading-with-your-agent/), [OAuth resource metadata](https://agent.robinhood.com/.well-known/oauth-protected-resource/mcp/trading), [OAuth server metadata](https://agent.robinhood.com/.well-known/oauth-authorization-server/mcp/trading).

## Operator-controlled discovery

Only run this after deciding to connect your account. Robinhood may present Agentic account onboarding; the human completes or declines it. Do not paste credentials into an agent conversation.

```sh
uv run rh broker-discover --connect
```

The command prints an official login URL, listens temporarily on loopback, checks OAuth state, and delegates PKCE/issuer handling to the MCP SDK. Credentials are stored under the macOS Keychain service `trading-robinhood:official-mcp:v1`. No file-storage fallback is allowed. The catalog is saved with mode 0600 under ignored `.state/`; no brokerage tool is called or enabled by discovery.

Review the captured schemas and their hashes against the public docs. Keep `config/approved-market-tools.json` empty until reviewed structured input/output contracts are available. Unknown, changed, paginated-in-a-loop, malformed, or unstructured contracts are rejected. Account, preview, placement, cancellation, and watchlist/scan writes remain outside the read-client allowlist.

OAuth failure, expiry, rate limiting or server errors must not be treated as permission to bypass the gate. Discovery and read calls do not automatically retry trading operations; no trading transport is implemented.

```sh
uv run rh broker-logout
```

Logout deletes local Keychain items. Also disconnect the integration in Robinhood to revoke server-side access. Disconnecting does not prove working orders were canceled.
