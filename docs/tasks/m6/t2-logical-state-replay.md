---
task: M6-T2
issue: 163
status: completed
depends_on: [154, 162]
created_at: 2026-08-22
started_at: 2026-08-23
completed_at: 2026-08-23
completion_pr: 223
merge_sha: 5d39017a1e58065f22df66844c48c1473428caaf
---
# M6-T2 — Replay Timeline Logical State

- Replay Logical Journal to exact committed `TimelineVersion`.
- Reconstruct World Time, logical Work lifecycle/target/due/order, and chronology-budget position.
- Combine with M6-T1 materialization for historical reconstruction.
- Never reconstruct lease/fence/attempt/backoff/error as semantic history.
- Support initial version and Event-only/Work-only/time-only versions; reject gaps/inconsistency.

## Acceptance
- [x] Historical Pending Work intervals are exact.
- [x] World Time comes only from time transitions.
- [x] Budget/order restore exactly after restart.
- [x] Operational retry noise cannot change reconstruction.
- [x] InMemory/PostgreSQL parity + standard gates pass.

Architecture: `world-runtime.md`; A0002 §3.

## Verification evidence

- `python3 tools/check_architecture.py` → storage SQL ownership and Loom architecture dependency checks passed.
- `cargo fmt --all -- --check` → passed.
- `cargo check --workspace --all-targets --all-features` → passed.
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` → passed.
- `cargo test --workspace --all-features` → all workspace tests passed.
- `LOOM_REQUIRE_POSTGRES_TESTS=1 bash tools/test.sh --workspace --all-features` → all PostgreSQL 18 and workspace tests passed.
- `RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps` → passed.
- Focused `cargo test -p loom-runtime --lib logical_replay` → 3 tests passed, covering version zero, Event/Work/time intervals, chronology/order, technical metadata exclusion and deterministic corruption failures.
