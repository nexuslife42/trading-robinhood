# Implementation ledger — docs/foundation-plan.md

## Preflight

- Git 2.54.0 works. Workspace initially empty. No parent or global AGENTS.md. uv and Codex installed; gh missing.
- Connected GitHub identity is carolinaminted (229517478). Use repository-local Git identity with GitHub noreply email.
- Ruling: work in the current workspace on a feature branch, without a second worktree — user explicitly requested the current workspace; there is no existing code to isolate. Cost: no separate checkout for simultaneous edits.
- Ruling: the conversation-approved plan is the spec; persist it here and track tasks in this ledger instead of generating a second approval cycle. Cost: implementation details are governed by tests and recorded decisions.
- Shared interfaces: policy, execution, simulator, and broker use the same validated OrderIntent, Quote and AccountSnapshot. Approvals bind the canonical order/policy/release/preview digests. Simulator and transport normalize execution results into OrderStatus.

## Tasks

- Task 1: engineering foundation — in progress.
- Task 2: policy, state and simulation — pending.
- Task 3: guarded MCP / connected validation — pending.
- Task 4: operator/release/recovery and final review — pending.
