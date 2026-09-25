# Operator and release guide

All executable order commands in this version operate on simulated money. `rh live` is intentionally unavailable. Do not change that rejection to make a check pass.

## Normal checks

```sh
uv sync --locked
make check
make replay
make audit
make secrets
make build
```

CI runs the same quality, simulation and security checks. It never receives Robinhood credentials. A green replay means the software matched the test's assumptions, not that a strategy would make money.

## Paper operator workflow

Use one explicit ledger path throughout an exercise. Load a JSON Quote using `uv run rh quote quote.json --state .state/paper.sqlite3`; its timestamp must be current UTC. Propose an OrderIntent with `uv run rh propose order.json --state .state/paper.sqlite3 --policy config/paper.toml`. The example policy accepts only the synthetic SYNTH instrument.

```sh
uv run rh approve-execute ORDER_ID --state .state/paper.sqlite3 --policy config/paper.toml
uv run rh status --state .state/paper.sqlite3
```

Approval requires an interactive terminal and typing the displayed order ID and digest. It covers the exact proposal, preview, policy, and release, expires after 60 seconds by default, and is consumed before submission. It cannot be piped in or supplied as an agent tool. Starting a new executor clears unused approvals. The interactive commands do not fetch live quotes or run a background market feed.

After approval and submission, advance the **same ledger** with a synthetic tick:

```sh
uv run rh paper-tick tick.json --state .state/paper.sqlite3
uv run rh history ORDER_ID --state .state/paper.sqlite3
```

The tick file uses the replay tick format. For example:

```json
{"at":"2026-09-25T14:00:01Z","instrument":"SYNTH","bid":"9","ask":"10","liquidity":"1"}
```

Choose a timezone-aware timestamp after submission on the same UTC day. A later day expires DAY orders. Each tick supplies a shared maximum number of shares (`liquidity`) and must have a strictly later timestamp than the previous tick for that instrument. Repeating a tick fails, including after a restart. Use decimal strings for prices and quantities. `tradable` and `market_open` default to true; set either to false to prevent fills.

`paper-tick` requires an explicit ledger path, never approves or submits orders, and reports updated orders and the simulated portfolio. Already submitted orders can fill while halted, just as halt does not cancel them. Proposals cannot fill. With two one-share ticks at $10, a two-share buy starting from $1,000 ends at $979 and two shares, including the $1 order fee. The default connected MCP server still uses the deny-all policy; a rehearsal server must be started explicitly with `--policy config/paper.toml` and the same ledger path. No new MCP tools are added.

The simulator commits each tick and its balances together before updating executor history. If the command is interrupted after that commit, do not invent a new tick to retry it: use `history` and `reconcile` for the affected orders first. Their authoritative simulated fills remain in the ledger. The replay command continues to use its own temporary ledger and does not advance this one.

Status, history, and backup commands preserve existing approvals and halt state. They do not start an executor or reconcile orders.

## Timeout or crash

Keep the original request ID and ledger. Never create another request to retry an uncertain submission.

```sh
uv run rh halt --state .state/paper.sqlite3
uv run rh status --state .state/paper.sqlite3
uv run rh history ORDER_ID --state .state/paper.sqlite3
uv run rh reconcile ORDER_ID --state .state/paper.sqlite3 --policy config/paper.toml
```

`unknown`, `submitting`, and `cancel_pending` retain reservations and prevent resume. Reconciliation does not automatically clear the halt. For paper state, inspect the original simulator ledger and the event trail. If the original record is absent or damaged, leave it halted and preserve a backup; do not manufacture a terminal status. Start a separate, clearly new paper exercise only after preserving the old evidence. A future real broker adapter must resolve this with the broker's authoritative history or support, not manual SQL guesses.

After every unresolved order is reconciled and the operator decides to continue:

```sh
uv run rh resume --state .state/paper.sqlite3
```

Halt blocks new orders; it does not cancel working orders or undo trades. To cancel a known open paper order, run `uv run rh cancel ORDER_ID` with the same state and policy. Always inspect the returned status: a fill can win the race.

## Backup and restore

```sh
uv run rh backup .state/paper-backup.sqlite3 --state .state/paper.sqlite3
```

Use a new destination each time. Keep backups encrypted and outside Git. Stop the MCP server and every operator process before restoring. Preserve the damaged database and its WAL/SHM sidecars as evidence. Restore a backup to a **new ledger path**, run `uv run rh halt --state NEW_PATH`, inspect status, and reconcile every submitted order before considering resume. Never roll back only the ledger while keeping a newer broker or simulator state.

## Release promotion

1. Open a topic PR into staging. Inspect the change and run all required checks. Merge only after they pass.
2. Open staging → main. The merge candidate must pass all four checks again. Resolve review findings before merging.

Because main receives a merge commit, later topic branches must also merge the latest `origin/main` before their staging PR (see README). If a release PR is behind main, create `chore/sync-main` from current staging, merge `origin/main`, and submit that branch through the normal staging checks. Do not weaken the up-to-date gate or force-push staging.

3. Check out the exact main commit in a clean workspace. Build and smoke-test the wheel with locked runtime dependencies in a separate environment:

```sh
mkdir -p artifacts
uv build --no-sources
uv export --locked --no-dev --no-emit-project --output-file artifacts/runtime-requirements.txt
uv venv .runtime/release --python 3.13
uv pip sync --python .runtime/release/bin/python artifacts/runtime-requirements.txt
uv pip install --python .runtime/release/bin/python --no-deps dist/trading_robinhood-0.1.0-py3-none-any.whl
.runtime/release/bin/rh doctor
.runtime/release/bin/rh replay examples/synthetic-replay.json
shasum -a 256 dist/trading_robinhood-0.1.0-py3-none-any.whl
```

Use the actual wheel version if it changes. Keep the checksum and CI evidence with the release record. Then create a manifest using the intended policy and a fresh filename (replace `RELEASE_ID` with the commit ID):

```sh
uv run rh release-manifest artifacts/RELEASE_ID-manifest.json --root . --policy config/disabled.toml
uv run rh verify-release artifacts/RELEASE_ID-manifest.json --root . --policy config/disabled.toml
```

The manifest records exact file hashes, source commit and policy identity. It is not signed, does not itself run tests, and never grants trading authority. Link the commit's successful CI run and built artifact checksum in the release record. Do not claim verification for a different commit, policy, package or dataset. Keep the same built artifact for later deployment; never run a moving branch head as a live release.

No workflow deploys or starts trading. A future activation requires the broker contract and account gates to be implemented and certified. Code rollback also requires halting and reconciling existing orders first; it cannot undo a filled order.

## GitHub gates

The public repository requires PRs plus `quality`, `simulation`, `security`, and `branch-flow` on main and staging. Force pushes and deletion are disabled and admins are included. There is one human owner, so a separate mandatory reviewer count is zero; the owner still reviews and chooses each merge.

GitHub native secret scanning, push protection, and dependency alerts are enabled in addition to CI scans. These detect supported patterns; they cannot guarantee that all private financial data will be recognized. Keep runtime data out of every commit. Configuration API: [repository security settings](https://docs.github.com/en/rest/repos/repos#update-a-repository).

To reapply the stored branch policy after a deliberate configuration change:

```sh
gh api --method PUT repos/nexuslife42/trading-robinhood/branches/staging/protection --input config/branch-protection.json
gh api --method PUT repos/nexuslife42/trading-robinhood/branches/main/protection --input config/branch-protection.json
```

Do not use admin bypass or disable checks to merge. Confirm remote protection with the corresponding GET endpoints before calling a release protected.
