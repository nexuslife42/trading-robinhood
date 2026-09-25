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
- The initial 64 tests passed locally, including approval mutation/expiry/replay, timeout after acceptance, crash before recording, storage failure, concurrent dispatch lock, fill/cancel races, pending reservations, malformed schemas, release tampering, and actual STDIO MCP startup. Review added eight regression cases, bringing the suite to 72.
- Ruff lint and formatting pass. Strict mypy passes for all 14 source modules. Coverage is informational; subprocess CLI tests are not counted in the parent coverage process. Broker login is not covered by these offline checks.
- pip-audit found no known vulnerabilities in installed dependencies. Editable project code is excluded from this dependency advisory scan and reviewed separately.
- Built the wheel and source archive, installed the wheel in a separate environment with locked runtime dependencies, and ran doctor/replay there. The synthetic fixture produces two shares and $979 fake cash from $1,000 after a $1 fee.
- `codex mcp get personal_trading_paper --json` loads the intended command and five-tool allowlist. This installed alpha CLI rejects strict-config for MCP commands; no strict-mode or extension-permission verification is claimed.
- GitHub GET confirms main and staging require quality, simulation, security, branch-flow, up-to-date branches, PRs, resolved conversations and administrator enforcement. Force push and deletion are disabled. Required outside approval count is zero for the solo owner.
- GitHub native secret scanning and push protection are enabled; dependency alerts return HTTP 204 (enabled). Dependabot update PRs target staging and do not auto-merge.
- A read-only workflow probe identified missing recovery/package instructions and status invalidating approvals. The guide now includes wheel-install commands, per-release manifest names and order history; the status regression is tested.

## Final review and promotion

Independent whole-branch review examined bootstrap `f18163b` through `ddad572`. No Critical or Minor findings were raised. Three Important findings were reproduced and fixed with failing-then-passing tests:

- Credential-safe failure handling: malformed OAuth/transport exceptions no longer print rejected token values or raw response text. Regression: `test_discovery_errors_never_print_credentials`.
- Offline schema resolution: reject external dynamic references and use an explicit non-retrieving registry for both inputs and outputs. Regression: `test_remote_schema_references_never_reach_network`.
- Durable uncertainty blocking: unresolved ledger states block execution even if the halt write failed; an in-memory halt covers the existing process, and reconciliation preserves a durable halt until manual resume. Submission and cancellation regressions: `test_failed_uncertainty_write_blocks_existing_executor_until_manual_resume`.

The first GitHub run passed simulation, security and branch-flow but failed Linux mypy because the platform guard made the Keychain backend type indeterminate. A typed backend factory fixes both Linux and macOS checks without changing the runtime guard or relaxing strict typing.

- Final Ruling: authenticated OAuth interoperability, account eligibility, previews, and live execution remain outside offline review. They stay disabled pending connected certification; the cost is that this release cannot trade real money.
- Final Ruling: remote protections/CI are verified by the primary implementer, since the reviewer had read-only local scope. No failed check will be bypassed.
- Final Ruling: exchange realism remains limited to the documented simulator assumptions. Replay verifies this model and cannot establish real fill quality or performance.

Feature PR: https://github.com/nexuslife42/trading-robinhood/pull/1. Required CI is rerun after the review fixes. No Robinhood login, real account data, or real order has been used. No merge activates trading.

## Release handoff verification (2026-09-24, America/New_York)

- Confirmed feature PR #1 merged into staging at `9983e080ddd2c2c342ff2ed6d23d53062778cab8`. Release PR #2 is open; its original candidate passed all four required checks. The documentation branch explains how future topic branches include main's release history without bypassing protections.
- Rechecked both remote branch protections: four required checks, strict up-to-date enforcement, PRs, resolved conversations, administrator enforcement, and no force pushes or deletion. Public visibility, secret scanning, push protection, and dependency alerts remain enabled.
- Fresh local verification on the documentation branch passed: locked dependency sync, 72 tests, Ruff lint/format, strict mypy, synthetic replay ($979 cash and two SYNTH shares), dependency audit, and full-history Gitleaks. No application behavior changed during this handoff.
- Final promotion evidence will be stored locally in `artifacts/RELEASE_ID-release-record.md`, alongside the exact main commit's disabled-policy manifest and built wheel checksum. This avoids changing the source commit merely to record its own final hash. The record must link the successful release PR and main CI run; it does not grant live authority.
- The user-reported Codex context-window settings and VS Code's effective context window were not verified during release promotion. No machine-wide settings were changed.

## Persistent paper ticks (2026-09-24, America/New_York)

- Added `rh paper-tick FILE --state LEDGER` to advance one explicit synthetic market tick in an existing paper ledger. It updates submitted orders and executor history and reports the resulting simulated portfolio. It cannot approve or submit an order and adds no MCP tools. The default connected server remains deny-all; the rehearsal uses a separate ledger and an explicitly selected synthetic policy.
- Tick timestamps must increase per instrument. The marker, quote, fills, and balances commit together so repeated ticks cannot supply duplicate liquidity after restart. A failed transaction rolls them back together. Halt continues to block new submissions while previously submitted orders may fill.
- Independent review reproduced an interleaving issue between tick application and history/portfolio reporting. A regression failed before the fix. `Executor.advance_paper` now holds the ledger lock through tick application, reconciliation, and portfolio capture; its internal reconciliation helper shares the existing validation and uncertainty handling. Follow-up review found no remaining Critical or Important issues.
- Fresh verification passed: locked dependency sync, 82 offline tests, Ruff lint and formatting, strict mypy, the existing replay ($979 and two SYNTH shares), dependency audit, and full-history Gitleaks. New coverage includes unapproved proposals remaining unfilled, persistent duplicate-tick rejection, failed-tick rollback, lock scope, and a real local STDIO MCP proposal followed by CLI ticks and MCP restart verification. Test approvals remain confined to synthetic test fixtures.
- A separate local MCP rehearsal proposal for two synthetic SYNTH shares at a $10 limit was prepared. The operator handoff refreshes its quote and invokes the existing interactive approval CLI; it never supplies approval input. The operator completed exact-order approval in their terminal. The same-ledger run verified open → partial → filled, $979 fake cash and two SYNTH shares after the $1 fee, matching CLI/MCP history, and persistence after MCP restart. Saved evidence and the read-only ledger inspection confirmed the result. No Robinhood connection or real order was used. Runtime evidence and the handoff script are ignored local artifacts, not public repository content.
- Limitation: tick balances commit before per-order history reconciliation. If interrupted in between, inspect and reconcile the persisted simulator orders before another tick. This change does not claim atomicity across those separate commits or add exchange realism beyond the existing simulator.
