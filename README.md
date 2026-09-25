# Personal Robinhood trading foundation

A local Python workspace for developing, testing, and reviewing a Robinhood MCP integration. Real order submission is deliberately unavailable in this version. No strategy or investment recommendation is included.

## Start

```sh
uv sync --locked
uv run rh doctor
make check
make replay
```

Python 3.13 is managed by uv. VS Code tasks are available through **Terminal → Run Task**. Open this folder and select `.venv/bin/python` as the Python interpreter.

`make replay` runs an explicit synthetic order through the policy, approval, ledger, and fill simulator. It starts with $1,000 of fake cash, buys two fake SYNTH shares at $10, and charges a $1 fee. The expected final cash is $979. It uses no credentials or network connection. The fixture is a software test, not a strategy or performance claim.

## Development workflow

Topic branch → pull request into `staging` → tests and review → release pull request into `main`.

Use `feat/`, `fix/`, `chore/`, `docs/`, or `test/` names. Both protected branches require `quality`, `simulation`, `security`, and `branch-flow`. Administrators are subject to these rules. A merge never starts a trading process.

Start a change from staging and include the latest main history:

```sh
git fetch origin
git switch -c feat/your-change origin/staging
git merge origin/main
```

The merge is often a no-op. After a release, it brings main's release commit into your topic branch so the next staging → main PR can satisfy the up-to-date requirement. Resolve any conflicts on the topic branch, run the checks, and open its PR into staging. Never push directly to either protected branch.

The repository is **public at the owner's explicit request** so GitHub Free can enforce protections. Commit only code, instructions, synthetic fixtures, and sanitized schemas. Account data, tokens, runtime state, local logs, and private datasets must never enter Git, CI artifacts, issues, or PRs.

## What works

- Decimal-safe validation, a deny-all default policy, exact-order approvals, pending exposure limits, and durable SQLite order events.
- Paper limit orders, partial fills, cancellations, fees, slippage, and simplified sale settlement.
- Replay of timestamped fixtures with source/adjustment/license metadata and no future-tick access.
- A credential-free MCP server for paper proposals and status, with no approval or submission tool.
- An explicit Robinhood OAuth/Keychain discovery command and a schema-pinned public-market read client. No tools are pre-approved.
- Halt, reconcile, backup, content-provenance checks, automated checks, and recovery instructions.

## What remains gated

`uv run rh live` always exits with an error. A config flag or environment variable cannot enable it. Authenticated Robinhood discovery, account eligibility, account-response filtering, broker previews and live order mappings have not been certified. They need sanitized real contracts and tests before implementation can safely proceed. No claim of live readiness is made.

The simulator currently supports long-equity limit DAY orders. It does not model options, crypto, exchange holidays, corporate actions, queue position, or production market impact. Historical data may be imported in the fixture format only when these limitations are acceptable. Broker previews are not paper fills.

## Guides

- [Architecture and safety boundaries](docs/architecture.md)
- [Robinhood capabilities and connection](docs/robinhood.md)
- [Operator, release, and recovery guide](docs/operations.md)
- [Codex setup](docs/codex.md)
- [Approved foundation and acceptance criteria](docs/foundation-plan.md)
- [Implementation evidence and decisions](docs/implementation-log.md)

Use `uv run rh --help` for commands. The default policy rejects every order. Use `--policy config/paper.toml` only for the synthetic paper example.
