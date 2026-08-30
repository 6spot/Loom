---
task: SCHD-T11
issue: 413
status: planned
depends_on: [412]
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T11 — Add bounded round-robin cursor progression across Timeline pages

## Goal

Advance an in-process discovery frontier across bounded Supervisor cycles so
later stable Timelines cannot be permanently starved.

## Scope and acceptance

- [ ] Persist only an operational in-memory cursor and advance it from the T03
      continuation; wrap at the ordered scan end.
- [ ] Tolerate target creation/removal and reset safely when the cursor has no
      successor; treat the cursor as a hint, never persisted authority.
- [ ] Blocked/Idle/normal outcomes for an earlier target cannot starve later
      targets.
- [ ] Deterministic tests cover bounded repeated visits, wrap, blocked first
      target, deletion and later target addition.
- [ ] No reservation table, randomness, persistent cursor, weighted priority or
      per-target parallelism is introduced.

## Progress Log

- 2026-08-31 — Implementing the Supervisor's in-memory round-robin cursor by
  carrying the T03 exclusive continuation between bounded cycles and resetting
  it at the ordered scan end or when a cursor has no remaining successor.
- 2026-08-31 — Added deterministic Supervisor coverage for bounded repeated
  visits, end wrapping, a permanently blocked first target, cursor-adjacent
  terminalization, empty-page cursor recovery and later target creation.
- 2026-08-31 — Ledger governance reconciliation: the implementation candidate
  is prepared, but prerequisite SCHD-T10 remains canonically `in_progress`;
  task state is therefore kept `planned` until that dependency is reconciled.

## Verification Evidence

- `cargo fmt --all -- --check` — passed.
- `git diff --check` — passed.
- `cargo test -p loom-server --lib -j1` — passed: 19 tests.
- `cargo check --workspace --exclude loom-validator --all-targets
  --all-features` — passed.
- `cargo clippy --workspace --exclude loom-validator --all-targets
  --all-features -- -D warnings` — passed.
- `cargo test --workspace --all-features --exclude loom-storage
  --exclude loom-validator` — passed.
- `python3 tools/check_architecture.py` — passed.
- `python3 tools/check_storage_sql_ownership.py` — passed.
