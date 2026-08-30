---
task: SCHD-T13
issue: 415
status: completed
depends_on: [414]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at: 2026-08-30
completion_pr: 450
merge_sha: aa94ee0a7d4a835aecbaa641c9d83523ed81fea6
---

# SCHD-T13 — Wire SchedulerSupervisor into LoomServer build/run lifecycle

## Goal

Construct and run automatic Scheduler supervision as part of every successful
`loom-server` lifecycle without a configured Timeline target.

## Scope and acceptance

- [x] Build the Supervisor Runtime from the same registry, clock, budgets,
      failure policy and storage authority as the existing Scheduler path.
- [x] Construct it unconditionally, store it in `LoomServer`, and run it beside
      HTTP/Ingress under the shared shutdown signal; fatal errors request shared
      shutdown through existing patterns.
- [x] Preserve PostgreSQL CAS/fence authority and one current-thread loop.
- [x] Tests cover no-target startup, empty-store idle presence, fatal error
      propagation and coexistence of HTTP/Ingress/Supervisor.
- [x] Do not remove the old worker, config/env, add a service/container or add
      a disable flag; later cleanup leaves own those changes.

## Progress Log

- 2026-08-30 — Wired one target-neutral SchedulerSupervisor into the normal
  LoomServer lifecycle under the shared shutdown signal, with fatal-error
  propagation and no-target startup coverage.
- 2026-08-31 — Post-merge completion audit: delivery PR #450 merged as
  `aa94ee0a7d4a835aecbaa641c9d83523ed81fea6`; completion metadata and
  acceptance evidence are now reconciled on the canonical ledger.

## Verification Evidence

- `cargo fmt --all -- --check` — passed.
- `git diff --check` — passed.
- `cargo test -p loom-server --lib -j1` — passed.
- `cargo check --workspace --exclude loom-validator --all-targets
  --all-features` — passed.
- `cargo clippy --workspace --exclude loom-validator --all-targets
  --all-features -- -D warnings` — passed.
- `cargo test --workspace --all-features --exclude loom-storage
  --exclude loom-validator` — passed.
- `cargo test -p loom-storage --all-features --lib` — passed.
- `python3 tools/check_architecture.py` — passed.
- `python3 tools/check_storage_sql_ownership.py` — passed.
- No-target startup smoke test reached the `loom-server` listening log against
  a fresh PostgreSQL database.
- PR #450 CI run `33325802424` — Rust checks passed; the merged integration
  commit is recorded above. The ledger lane was correctly skipped because the
  delivery PR did not modify canonical task records.
