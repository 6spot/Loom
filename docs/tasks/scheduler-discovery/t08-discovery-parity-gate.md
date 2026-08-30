---
task: SCHD-T08
issue: 410
status: in_progress
depends_on: [406, 407, 409]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T08 — Prove InMemory/PostgreSQL Scheduler discovery contract parity

## Goal

Close Stage 2 with one Runtime-mediated behavioral matrix proving equivalent
InMemory and real PostgreSQL 18 discovery.

## Required matrix and acceptance

- [ ] No Pending, one Pending, duplicate same-Timeline Pending and
      terminal-only cases agree.
- [ ] Future-World-Time Pending Work is present on both backends.
- [ ] Multiple target identities, bound and continuation behavior are
      deterministic and equivalent.
- [ ] Repeated read is stable and discovery does not mutate Work/Timeline
      state.
- [ ] Required rows execute through Runtime on real PostgreSQL 18; no fake or
      self-skipped live evidence is counted.
- [ ] Relevant fmt/check/clippy/tests and the PostgreSQL gate pass.

Completion exposes T09 directly; Stage tracker `#400` closure is not a hard
dependency.

## Progress Log

- 2026-08-30 — Started the Runtime-mediated parity gate. The matrix will use
  equivalent seeded InMemory/PostgreSQL 18 fixtures, compare bounded pages and
  continuation through `Runtime::discover_scheduler_targets`, and assert that
  repeated discovery leaves Work/Timeline snapshots unchanged.
- 2026-08-30 — Added the shared Runtime-mediated matrix in
  `crates/loom-storage/tests/scheduler_discovery_parity.rs`; no T03–T07 source
  or fixture files were changed, so there is no overlap with the active ME-307
  tracker implementation files.

## Verification Evidence

- `bash tools/test.sh -p loom-storage --test scheduler_discovery_parity -- --nocapture`
  — passed: both parity tests executed against the repository-managed
  PostgreSQL 18 service and InMemory; all matrix rows passed.
- `bash tools/test.sh -p loom-storage --all-targets --all-features` — passed:
  65 storage unit tests and all storage integration targets, including the
  PostgreSQL 18 discovery adapter and Runtime parity tests.
- `cargo check --workspace --all-targets --all-features` — passed.
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` —
  passed.
- `cargo fmt --all -- --check`, `git diff --check`,
  `python3 tools/check_architecture.py` and
  `python3 tools/check_storage_sql_ownership.py` — passed.
- `bash tools/test.sh --workspace --all-features` was attempted but the host
  filesystem exhausted its remaining space while linking unrelated workspace
  test binaries (`ld: No space left on device`); no test assertion failure was
  reported. The task remains in progress pending review/merge and the host
  resource limitation is recorded here for the handoff.
