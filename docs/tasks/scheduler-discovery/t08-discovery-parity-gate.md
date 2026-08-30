---
task: SCHD-T08
issue: 410
status: completed
depends_on: [406, 407, 409]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at: 2026-08-30
completion_pr: 443
merge_sha: aa409ed331c4c17a5978be390b1982fa2a195e08
---

# SCHD-T08 — Prove InMemory/PostgreSQL Scheduler discovery contract parity

## Goal

Close Stage 2 with one Runtime-mediated behavioral matrix proving equivalent
InMemory and real PostgreSQL 18 discovery.

## Required matrix and acceptance

- [x] No Pending, one Pending, duplicate same-Timeline Pending and
      terminal-only cases agree.
- [x] Future-World-Time Pending Work is present on both backends.
- [x] Multiple target identities, bound and continuation behavior are
      deterministic and equivalent.
- [x] Repeated read is stable and discovery does not mutate Work/Timeline
      state.
- [x] Required rows execute through Runtime on real PostgreSQL 18; no fake or
      self-skipped live evidence is counted.
- [x] Relevant fmt/check/clippy/tests and the PostgreSQL gate pass.

Completion exposes T09 directly; Stage tracker `#400` closure is not a hard
dependency.

## Progress Log

- 2026-08-30 — Prepared the Runtime-mediated parity gate. The matrix uses
  equivalent seeded InMemory/PostgreSQL 18 fixtures, compares bounded pages and
  continuation through `Runtime::discover_scheduler_targets`, and asserts that
  repeated discovery leaves Work/Timeline snapshots unchanged.
- 2026-08-30 — Added the shared Runtime-mediated matrix in
  `crates/loom-storage/tests/scheduler_discovery_parity.rs`.
- 2026-08-30 — Delivery PR #443 merged as
  `aa409ed331c4c17a5978be390b1982fa2a195e08`; canonical completion metadata is
  reconciled here.

## Verification Evidence

- `bash tools/test.sh -p loom-storage --test scheduler_discovery_parity -- --nocapture`
  — passed against repository-managed PostgreSQL 18 and InMemory.
- `bash tools/test.sh -p loom-storage --all-targets --all-features` — passed.
- `cargo check --workspace --all-targets --all-features` — passed.
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` — passed.
- `cargo fmt --all -- --check`, `git diff --check`,
  `python3 tools/check_architecture.py` and
  `python3 tools/check_storage_sql_ownership.py` — passed.

The workspace-wide test attempt exhausted host disk while linking unrelated
binaries; focused parity/storage PostgreSQL 18 gates and required PR CI passed.
