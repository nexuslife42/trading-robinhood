---
name: trading-workflow
description: Use when validating a release, reviewing Robinhood MCP capability changes, or recovering an uncertain order in this trading-robinhood repository.
---

Read `docs/operations.md` from the repository root for the exact checks and recovery commands. For a connection or schema change, also read `docs/robinhood.md`. These guides describe the implemented boundary; do not infer a live command from paper commands.

For release work, report the source commit, intended policy, exact checks and results, PR/CI links, and remaining gates. A manifest proves content consistency, not test success or live authorization. Verify remote main/staging branch protections before calling a release protected.

For an uncertain order, identify the original ledger and request ID, halt, inspect, and reconcile. Keep the halt if the result is unknown. Do not create another request to retry a timeout or manually overwrite ledger state to force a terminal result. State what remains unresolved.

For capability work, discovery captures metadata only. Keep account/preview/write tools disabled until their specific contracts, filters, and tests exist. Public-market tool approval needs the exact captured schema hash and validated structured output.

This skill grants no broker login, trading, publishing, or merge permission beyond the user's existing authorization.
