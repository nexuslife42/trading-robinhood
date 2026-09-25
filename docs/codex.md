# Codex and VS Code setup

The installed Codex CLI was `0.155.0-alpha.16.3` at setup. Features and settings can change; validate configuration with this installed version and official documentation before upgrading. Python/MCP dependencies are pinned in `uv.lock` and CI tool versions are fixed.

The project config registers only the local paper MCP server. It does not register Robinhood directly or alter machine-wide settings. After trusting the project and restarting the Codex extension, inspect the MCP tools. Expected tools are `foundation_status`, `paper_portfolio`, `propose_paper_order`, `paper_order_status`, and `halt_paper`. No approve, submit, generic forwarding, or live tool should appear from this server.

`codex mcp get personal_trading_paper --json` confirms the installed CLI loads the project command and five-tool allowlist. This version does not support `--strict-config` with `codex mcp`; that command is not evidence of strict validation or of the extension's effective permissions. The test suite also starts the actual STDIO server and checks its paper-only response.

Use the VS Code task picker for tests, lint, types, replay, status, and doctor. Nothing runs on editor startup. The standard server starts with the deny-all policy; use a separate explicitly configured paper session to exercise the synthetic example.

## Permissions

Development uses workspace-write with human review of escalations. Project configuration cannot establish a separate operating-system identity. Global MCP servers, plugins and app connectors may still be inherited; inspect the effective tool list instead of assuming this project config removes them. The command sandbox does not automatically control all connector, MCP, browser, and computer-use traffic.

Do not attach the official Robinhood server to ordinary coding sessions. Use the explicit operator discovery command instead. Broker credentials belong only in Keychain, never a config file, shell argument, environment file, CI secret, conversation, or test fixture.

For a future live session, require human approvals, disable automatic approval review, editing, shell execution, browser/computer control and unrelated integrations, and verify effective controls before activation. If the installed client cannot enforce those controls, keep live disabled. No live profile is supplied here because the execution contract has not been certified.

## Skills and reviewers

The project workflow skill links to the release and incident runbook. Root AGENTS.md holds the invariants. These files guide an agent; tested application code enforces the implemented gates.

Give reviewer agents read-only code access with a concrete change range and acceptance criteria. They must not receive broker credentials, modify policy, or execute real orders. Keep independent implementation tasks on separate branches/worktrees if needed; merge through the same checks.

Sources: [MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli), [approval boundaries](https://learn.chatgpt.com/docs/agent-approvals-security), [project instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md).
