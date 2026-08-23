---
task: M7-T6
issue: 173
status: planned
depends_on: [168, 169, 170, 171, 172]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M7-T6 — Read/projection/blob authority gate

Across parent/child Timelines and multiple bindings: exercise catalogs, trajectory/causal queries, projection build/query/delete/rebuild, blobs and a long pinned read racing a commit.

## Assertions
- [x] World Catalog never exposes disabled semantics as executable.
- [x] History/causal visibility respects ancestry and bounds.
- [x] Projection changes cannot change authority/replay/fork.
- [x] Semantic ReadSet records projection dependency.
- [x] Missing/corrupt blob changes only blob access.
- [x] Pinned reads remain one-version consistent without full-World PostgreSQL load.
- [x] Benchmark limits/evidence are recorded without unsupported scale claims.
- [x] Architecture/fmt/check/clippy/tests/rustdoc + PostgreSQL18/pgvector/blob suites pass.

## Verification evidence

Candidate baseline and scope:

- `72c0ee1164152b7027f2670c4ec9547f031527ab` is the ME-209 `origin/main` base.
- `a540eaa` is the linear ME-210 foundation integration and `543ae72` is its metadata-preserving duplicate-put fix; both are retained unchanged.
- The ME-212 candidate adds one existing composition test in `tests/loom-composition/vertical_slice.rs`; no Runtime/Storage public boundary, dependency or schema is added.

AC mapping and race evidence:

- AC-1: the composition gate uses two World Bindings, checks global vs scoped catalogs, forks a parent/child Timeline through the authority port, verifies Entity and Relationship trajectories, excludes parent-future Events, and checks bounded causal refs/walks.
- AC-2: the gate registers/builds/queries/deletes/rebuilds projection revision 1, restarts Runtime, then registers/builds/queries revision 2 with a changed model. Authority version/Event/base snapshots remain equal before and after projection mutation. The Runtime semantic host test records ordered `ReadDependency::Semantic` evidence and leaves the ReadSet empty on a bounded failure.
- AC-3: duplicate puts remain idempotent, metadata mismatch/corruption/missing are typed, local adapter reopen preserves bytes, and the existing injected object-store adapter contract covers S3-compatible behavior. Blob operations leave authority Events unchanged.
- AC-4: the gate performs an exact-version cached read, races a commit against a pinned read, accepts only a consistent pre-commit value or `PinnedVersionMismatch`, invalidates through a fresh zero-cache boundary, and restarts under `PinnedReadPolicy(1, 2)`.
- AC-5: Runtime, projection adapter, local Blob adapter and pinned-read boundaries are restarted in the composition/contract scenarios. PostgreSQL adapter restart and version fencing are covered by the pinned-read suite.
- AC-6: the gate prints `adapter=InMemory backend=local world_size=2 rows=1 bytes=16 latency_us=12 cache_capacity=2 max_restarts=1` in this run. The PostgreSQL pinned-read fixture records `world_size=1/32/256`, `rows=1`, `bytes=36`, and `latency_us=4859/1708/1906`; these are fixture measurements only.

R-* evidence:

- R-1 projection expected-revision fence and delete/rebuild are the adapter write boundaries; no projection operation changes the authority snapshot.
- R-2 Blob first put is immutable; later duplicate puts compare metadata, while corruption/missing only changes Blob read results. Replay remains unchanged in the Blob contract test.
- R-3 pinned read authority is one `(World, Timeline, TimelineVersion)` session. A commit racing the old session produces either the old version's complete read or the typed fence error; no mixed result is accepted.
- R-4 successful semantic host reads append ordered index/query/revision/source evidence; typed bounded failures append no success evidence.

Initial focused results from the integrated baseline:

- `cargo test -p loom-composition-tests --test vertical_slice -- --nocapture` → 12 passed.
- `cargo test -p loom-runtime --lib semantic_host_records_ordered_evidence_and_applies_session_bounds` → 1 passed.
- `cargo test -p loom-runtime --lib pinned_reads` → 3 passed.
- `cargo test -p loom-storage --test semantic_projection -- --nocapture` → 3 passed, including PostgreSQL/pgvector.
- `cargo test -p loom-storage --test pinned_reads -- --nocapture` → 4 passed, including PostgreSQL one-row reads/version fences.
- `cargo test -p loom-storage --lib blob -- --nocapture` → 5 passed, including local and injected object-store contracts.
- `cargo fmt --all -- --check` → passed.
- `python3 tools/check_architecture.py` → passed.
- `python3 tools/check_storage_sql_ownership.py` → passed.
- `cargo check --workspace` → passed.
- `cargo clippy --workspace --all-targets -- -D warnings` → passed.
- `RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps` → passed.
- `cargo test --workspace --all-features` → all workspace, PostgreSQL 18/pgvector, blob, pinned-read and doc tests passed.

D-* findings: none. No unverified items remain within the requested local/fixture scope; no real cloud credentials or unsupported scale claims were used.
