---
task: M7-T5
issue: 172
status: completed
depends_on: [150, 167]
created_at: 2026-08-22
started_at: 2026-08-23
completed_at: 2026-08-23
completion_pr: 226
merge_sha: 0bf4845a28e34bd4bbffc730e4793cbfa4775ebd
---
# M7-T5 — Scalable Pinned Read Boundary

- Pinned BaseWorldView means one TimelineVersion consistency, not mandatory full-World materialization.
- Runtime may use bounded lazy/cache/prefetch/version-fenced reads; every read is from pinned version or fails/retries before commit.
- Runtime owns storage/read ports + ReadSet; Capability receives no persistence authority.
- Candidate overlay still sees prior same-Resolution effects.
- PostgreSQL representative point/facet/relationship/event reads must demonstrate a non-full-snapshot path; InMemory may stay eager.
- Keep Timeline-wide CAS; do not introduce fine-grained commit validation in v0.
- Instrument rows/bytes/latency vs World size.

## Acceptance
- [x] Concurrent/version-advance fence cannot produce a mixed-version view.
- [x] Point read does not load whole PostgreSQL World.
- [x] Overlay/ReadSet semantics remain correct.
- [x] Restart/cache miss policy is bounded and deterministic; benchmark evidence recorded.

Architecture: A0003 §4/§5.

## Verification evidence

- `cargo fmt --all -- --check` → passed.
- `python3 tools/check_architecture.py` and `python3 tools/check_storage_sql_ownership.py` → passed.
- `CARGO_TARGET_DIR=/tmp/loom-me211-target cargo check --workspace` → passed.
- `CARGO_TARGET_DIR=/tmp/loom-me211-target cargo clippy --workspace --all-targets -- -D warnings` → passed.
- `CARGO_TARGET_DIR=/tmp/loom-me211-target RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps` → passed.
- `CARGO_TARGET_DIR=/tmp/loom-me211-target LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_me211_control cargo test --workspace --all-features` → all workspace, PostgreSQL 18, and doc tests passed on a fresh control database.
- Focused `cargo test -p loom-runtime --lib pinned_reads` → 3 tests passed for bounded restart policy, ReadSet positive/negative dependencies, and deterministic cache invalidation.
- Focused `cargo test -p loom-storage --test pinned_reads -- --nocapture` → 4 tests passed; PostgreSQL point/facet/relationship/event reads reported one-row point amplification and stale-version rejection. Benchmark output was `world_size=1/32/256`, `rows=1`, `bytes=36` for each target read.
