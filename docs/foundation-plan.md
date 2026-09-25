# Approved foundation plan

Approved in conversation on 2026-09-24. User confirmed implementation after installing Git 2.54.0. The user subsequently chose PUBLIC GitHub under nexuslife42 to obtain enforced branch protections without Pro. Other binding choices remain the current macOS user/workspace and approval of every real order.

## Deliverables

1. Reproducible Python 3.13 / uv package, public GitHub (owner's revised choice), feature/staging/main workflow, required CI, VS Code tasks, AGENTS.md and a focused workflow skill.
2. Typed broker interfaces, decimal-safe policy, persistent approvals/order events, fail-closed execution and deterministic paper/replay harness.
3. Official Robinhood MCP connection with Keychain OAuth, authenticated schema discovery, explicitly allowlisted reads/previews, and sanitized data. No undocumented account access or live testing.
4. Operator-only approval, release integrity verification, halt/reconciliation/recovery commands and tests. No live activation as part of development.

## Invariants and acceptance

No merge starts trading. No raw broker forwarding tool exposed to agents. No credentials in development/CI. Approval binds order, preview, release, and configuration. Persist intent before submit; ambiguous results halt and never auto-retry. Serialize and reserve exposure. New schemas, stale data, auth failure, storage failure and unsupported contracts fail closed. Reconcile after restart/sleep. Cancellation cannot undo a fill.

Test environment separation, approval mutation/expiry/replay, timeout/crash/duplicate submission, partial fills, cancellation races, limits and pending exposure, stale quotes, malformed tool responses, schema changes, prompt injection, release tampering, and restart recovery. Simulation uses synthetic fixtures first and explicit fill/fee/slippage/settlement assumptions. No strategy, instrument selection, capital allocation, or unattended schedule is in scope.

## Interfaces

BrokerAdapter: capabilities, snapshot, quote, preview, submit, cancel, and lookup. OrderIntent uses explicit asset class, account alias, instrument, side, quantity, order parameters, and request ID. PolicyDecision carries reasons and version. Approval binds canonical digests and an expiry. OrderEvent is durable, UTC-timestamped, and records broker IDs.

## Review focus

- Same-user tampering: do not claim isolation that profiles cannot provide.
- Submission uncertainty: no duplicate exposure after a crash or dropped response.
- Simulator accounting: partial fills and pending orders must reserve resources correctly.
- MCP drift/untrusted output: deny new tools and schemas and sanitize records.
- Release provenance: missing/changed inputs or evidence must prevent activation.

## External gates

GitHub authentication and enforced branch protection must be verified. Robinhood OAuth onboarding is completed by the human in a browser; authenticated capability schemas and account permissions are not available during offline development. Missing external evidence keeps live execution disabled, not guessed.

The initial implementation provides the OAuth/discovery mechanism and a tested schema-pinned public-market client. Authenticated discovery, account filters, broker previews, and real order adapters remain gated until the owner connects and actual contracts can be verified. No schemas or account permissions are guessed to close this external gate.

## Research

- https://robinhood.com/us/en/support/articles/agentic-trading-overview/
- https://robinhood.com/us/en/support/articles/trading-with-your-agent/
- https://agent.robinhood.com/.well-known/oauth-protected-resource/mcp/trading
- https://learn.chatgpt.com/docs/extend/mcp?surface=cli
- https://learn.chatgpt.com/docs/agent-approvals-security
- https://learn.chatgpt.com/docs/agent-configuration/agents-md
- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches

Public research date: 2026-09-24. Official hosted endpoint requires OAuth; public scope is `internal`. Do not infer read-only OAuth scopes, rate limits, idempotency, paper-account support, or undisclosed server contracts.
