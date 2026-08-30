---
task: SCHD-T12
issue: 414
status: completed
depends_on: [413]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at: 2026-08-30
completion_pr: 449
merge_sha: 57ab56ea8834b6732eb90a8afc03d7d3e1e2bbe3
---

# SCHD-T12 — Implement Supervisor polling loop + graceful shutdown

## Goal

Turn bounded Supervisor cycles into the long-running application loop using the
existing worker poll interval and shutdown contract.

## Scope and acceptance

- [x] Repeatedly run the T10/T11 cycle until shutdown, checking shutdown before
      each new cycle and sleeping only between cycles.
- [x] Reuse `worker_poll_interval`; platform sleep never advances World Time.
- [x] Let an active drive finish, propagate genuine discovery/Runtime errors,
      and keep normal Blocked/Idle outcomes non-fatal.
- [x] Async tests cover pre-start shutdown, one-cycle shutdown, empty/idle
      continuation and genuine errors.
- [x] No server wiring, new config, notification optimization or worker pool is
      introduced.

## Progress Log

- 2026-08-30 — Implemented the target-neutral Supervisor polling loop with
  existing poll timing, prompt shutdown observation and focused async coverage.
- 2026-08-31 — Post-merge completion audit: delivery PR #449 merged as
  `57ab56ea8834b6732eb90a8afc03d7d3e1e2bbe3`; completion metadata and
  acceptance evidence are now reconciled on the canonical ledger.

## Verification Evidence

- `cargo fmt --all -- --check` — passed.
- `cargo test -p loom-server --lib scheduler_supervisor -- --nocapture` —
  passed.
- `cargo check --workspace --exclude loom-validator --all-targets
  --all-features` — passed.
- `cargo clippy --workspace --exclude loom-validator --all-targets
  --all-features -- -D warnings` — passed.
- `cargo test --workspace --all-features --exclude loom-storage
  --exclude loom-validator` — passed.
- `cargo test -p loom-storage --all-features --lib` — passed.
- `python3 tools/check_architecture.py` — passed.
- `python3 tools/check_storage_sql_ownership.py` — passed.
- PR #449 CI run `33324591487` — Rust checks passed; the merged integration
  commit is recorded above. The ledger lane was correctly skipped because the
  delivery PR did not modify canonical task records.
