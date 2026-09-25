# Implementation ledger — docs/foundation-plan.md

## Decisions

- Git 2.54.0 works. The workspace was initially empty; no existing code or user changes were overwritten.
- Ruling: work in the current workspace on a feature branch without a second worktree, as requested. Cost: simultaneous edits do not have separate checkouts.
- Ruling: use the conversation-approved foundation plan as the spec rather than repeat approval. Tests and this ledger govern implementation details; a misunderstood requirement would need correction.
- The owner selected the CLI identity nexuslife42. The initial bootstrap commit used the previously connected identity; subsequent commits use the selected account's GitHub noreply address.
- GitHub Free rejected private branch protection. The owner explicitly chose public instead of Pro. Before changing visibility, the remote's seven bootstrap files and full history were reviewed and scanned with Gitleaks; no leaks were found. Code and all history are now public.
- Ruling: provide a long-equity limit DAY simulator as the reference implementation, not a trading strategy. Options, crypto, corporate actions, holidays, and production market impact require separate models before they can be tested credibly.
- Ruling: ship explicit OAuth/Keychain discovery and a schema-pinned public-market read client, with no approved tools. Authenticated schemas/account eligibility are unavailable without the owner's Robinhood onboarding. Account filtering, broker previews, and live execution remain unimplemented behind the gate; this costs a later connected certification step and prevents any claim of live readiness.
- Ruling: use one project workflow skill and AGENTS.md, with code enforcing the safety rules. More plugins do not create a security boundary. Arbitrary code running as the same user can bypass local controls.

## Implemented tasks

1. Engineering foundation: locked Python 3.13 package, feature/staging/main branches, public GitHub repository, required CI configuration, pinned Actions, VS Code tasks, project Codex config, AGENTS.md and workflow skill.
2. Policy/state/simulation: strict Decimal models, default-deny policy, exact approval binding, expiry/consumption, durable intent and event ledger, pending exposure reservations, timeout/crash halt, reconciliation, persistent paper fills and deterministic replay.
3. Guarded MCP: five local paper tools with no approve/submit tool, schema drift checks, validated public-market calls, explicit OAuth discovery using macOS Keychain and approved destinations. Real authenticated behavior is unverified and live is unavailable.
4. Operator/release/recovery: interactive paper approval, halt/resume/cancel/reconcile, status/history, consistent backups, content manifests, wheel builds and runbooks. Final branch review and remote CI results are recorded below when completed.

## Verification evidence (2026-09-24)

- Module tests were introduced before implementation; missing-module failures preceded working code. Restart approval invalidation and status/backup preservation regressions failed before their fixes. The history command was added after its missing-command test failed.
- 64 tests pass locally, including approval mutation/expiry/replay, timeout after acceptance, crash before recording, storage failure, concurrent dispatch lock, fill/cancel races, pending reservations, malformed schemas, release tampering, and actual STDIO MCP startup.
- Ruff lint and formatting pass. Strict mypy passes for all 14 source modules. Coverage is informational; subprocess CLI tests are not counted in the parent coverage process. Broker login is not covered by these offline checks.
- pip-audit found no known vulnerabilities in installed dependencies. Editable project code is excluded from this dependency advisory scan and reviewed separately.
- Built the wheel and source archive, installed the wheel in a separate environment with locked runtime dependencies, and ran doctor/replay there. The synthetic fixture produces two shares and $979 fake cash from $1,000 after a $1 fee.
- `codex mcp get personal_trading_paper --json` loads the intended command and five-tool allowlist. This installed alpha CLI rejects strict-config for MCP commands; no strict-mode or extension-permission verification is claimed.
- GitHub GET confirms main and staging require quality, simulation, security, branch-flow, up-to-date branches, PRs, resolved conversations and administrator enforcement. Force push and deletion are disabled. Required outside approval count is zero for the solo owner.
- A read-only workflow probe identified missing recovery/package instructions and status invalidating approvals. The guide now includes wheel-install commands, per-release manifest names and order history; the status regression is tested.

## Final review and promotion

Pending independent whole-branch review, public feature push, and required CI. No Robinhood login, real account data, or real order has been used. No merge activates trading.
