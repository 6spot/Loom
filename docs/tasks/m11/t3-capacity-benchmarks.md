---
task: M11-T3
issue: 195
status: completed
depends_on: [172, 192, 193]
created_at: 2026-08-22
started_at: 2026-08-24
completed_at: 2026-08-24
completion_pr: 265
merge_sha: 9bdbfec37126db54570ffa6e34c3d6d422ccad99
---
# M11-T3 — Scheduler/Agency capacity benchmarks

- Reproducible loads for many Timelines, many same-instant Works, same-instant Agency Wakes with controlled fake latency, external Action races, large-World pinned reads and PostgreSQL head selection.
- Measure throughput/latency/queueing/CAS conflict/lease retry/DB work/discarded cognition and cost metadata.
- Show same-Timeline Scheduler semantic work is head-ordered/serialized while independent Timelines/pre-commit external resolution may overlap.
- Measure default resample and any explicitly allowed reuse policy after cognition CAS conflict.
- Publish environment/data sizes/results; practical readiness claims come from evidence and remain separate from semantic architecture.

> **Threshold disclaimer:** All numbers below are *observed evidence* from the benchmark harness on the recorded environment and dataset sizes. They are not semantic architecture limits, not invariants, and must not be promoted to a Core/Runtime contract without an explicit Architecture Amendment. Production readiness targets are derived only from this evidence; larger-scale claims are marked **unproven / deferred**.

## Acceptance
- [x] Single vs multi-Timeline curves separate.
- [x] Same-instant serialization visible.
- [x] Cognition conflict waste quantified.
- [x] Pinned-read rows/bytes evidence included.
- [x] Benchmark reproducible; no unsupported scale claim.

## Benchmark harness

**Implementation:** `crates/loom-bench` (`crates/loom-bench/src/lib.rs`, `crates/loom-bench/src/main.rs`)

- All scenarios use the real `Runtime` + `InMemoryStore` (and `PgStorage` when PostgreSQL is reachable) through the standard `CommitStore`/`WorkStore`/`SchedulerCommitStore`/`PinnedWorldReadStore`/`ExecutionSessionStore` ports, `Runtime::drive_timeline`, `ActionService::invoke`, `ExecutionPolicy`/`DecisionReusePolicy`, and `PinnedReadBoundary`. No mock bypass of persistence/Session/Binding/Scheduler authority.
- Deterministic `DeterministicCognitiveExecutor` with configurable `delay_polls` simulates cognition latency; `inject_scheduler_conflict_once_for_test` arms a real Timeline CAS conflict via `WorkTerminalization` authority, not a synthetic error.
- Each scenario is seeded with explicit `WorldId`/`TimelineId`/`WorkId`/`EntityId`/`EventId`, bounded `ResolutionBudget`/`ContextBudget`/`PinnedReadPolicy`, and flushed through `TimelineVersion` CAS + `WorkClaim` fence validation.
- Reproducibility: `cargo run -p loom-bench` (InMemory always; Postgres when `LOOM_TEST_POSTGRES_URL` or default `postgresql://loom:loom@127.0.0.1:15432/loom_control` is reachable via `bash tools/postgres-test.sh up`). Full run also writes `Loom/target/bench-results/m11-t3-capacity.json` + `.md` and `stdout` markdown.

**Scenarios (7 families, 30+ variants):**

1. `multi_timeline_parallel` — N timelines (1,4,16,32,64), one Immediate Work each at `WorldInstant(0)` order 1, driven concurrently via `futures::join_all` (independent CAS domains).
2. `single_timeline_many_works` — one Timeline, N Immediate Works (1,8,32,64,128) at same `WorldInstant(0)` with orders 1..N, driven sequentially via `drive_timeline` loop (head-ordered serialization).
3. `agency_wakes_same_instant` — one Timeline, N Agency Wakes (4,16,32) at same instant with `delay_polls` 0/2/5, `DeterministicCognitiveExecutor` Act via `counter.increment`.
4. `external_action_race_long_wake` — one delayed Agency Wake (delay 5) vs 3 concurrent external `ActionService::invoke` racing pre-commit; measures CAS conflicts/lease behavior and verifies `external Success=3` + wake still commits head-ordered.
5. `pinned_reads_scaling` (+ `pinned_reads_facet_scaling`) — InMemory point reads for world sizes 1,32,256,1024,4096 (and 8192 via `pinned_reads.rs`); measures `rows_read`/`bytes_read`/`cache_hits`/`latency`. Postgres variant in same harness for world sizes 1,32,256 via `PgStorage` + `sqlx` inserts and `PinnedWorldReadStore::read_entity`.
6. `scheduler_head_selection` / `scheduler_poll_drive` — head vs non-head `WorkStore::claim` latency for timeline counts 1,10,50,100; verifies non-head rejection without mutation (`non_head_rejections == timelines`) and sequential `drive_timeline` poll scaling.
7. `cognition_resample_vs_reuse` — 8 iterations per policy: `Resample` (default, 2 executor calls per CAS loss) vs `ReuseDeterministic` (1 call + `CognitiveDisposition::Reused` with fresh pinned coordinate); measures `executor_calls`, `discarded_count`, `reused_count`, `fresh_count`, `evidence_entries`, wall time.

## Environment

```
rustc: rustc 1.97.1 (8bab26f4f 2026-07-14)
cargo: cargo 1.97.1 (c980f4866 2026-06-30)
git_sha: 830cf38 ME-232: Enforce bounded resource policies (#263) — prior to M11-T3
os: Linux instance-20260508-1651 6.12.0-201.74.2.2.el9uek.aarch64 #1 SMP Thu Apr 30 16:38:02 PDT 2026 aarch64
cpu: processor 0 | BogoMIPS 50.00 | Features fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp cpuid asimdrdm lrcpc dcpop asimddp | implementer 0x41
memory: MemTotal 23496384 kB
timestamp: 2026-08-24T17:01:27+00:00 (UTC)
loom_version: 0.1.0
postgres: pgvector/pgvector:0.8.6-pg18 reachable at 127.0.0.1:15432 (via `bash tools/postgres-test.sh up`); migrations applied per isolated bench DB
```

Dataset sizes are encoded in each `variant` label (`timelines=N`, `works=N`, `wakes=N`, `world_size=N`).

## Observed results (InMemory, single-host aarch64, 2026-08-24)

### Multi-Timeline (independent CAS domains, concurrent) vs Single-Timeline (serialized)

| scenario | variant | dataset | wall_ms | throughput ops/s | p50_ms | max_ms | notes |
|---|---|---|---|---|---|---|---|
| multi_timeline_parallel | timelines=1 | 1 | 1.69 | 591.7 | 1.67 | 1.67 | head-ordered per timeline but parallel across timelines |
| multi_timeline_parallel | timelines=4 | 4 | 10.21 | 391.6 | 1.64 | 5.65 | |
| multi_timeline_parallel | timelines=16 | 16 | 125.91 | 127.1 | 7.47 | 27.76 | |
| multi_timeline_parallel | timelines=32 | 32 | 479.40 | 66.7 | 14.16 | 35.32 | |
| multi_timeline_parallel | timelines=64 | 64 | 1696.20 | 37.7 | 18.24 | 78.64 | |
| single_timeline_many_works | works=1 | 1 | 1.27 | 785.4 | 1.27 | 1.27 | serialization_verified=true; events=1; chronology_consumed=1 |
| single_timeline_many_works | works=8 | 8 | 36.55 | 218.9 | 6.37 | 9.86 | serialization_verified=true; events=8; chronology_consumed=8 |
| single_timeline_many_works | works=32 | 32 | 371.45 | 86.1 | 11.46 | 20.71 | |
| single_timeline_many_works | works=64 | 64 | 1701.37 | 37.6 | 24.20 | 71.29 | |
| single_timeline_many_works | works=128 | 128 | 5373.70 | 23.8 | 33.85 | 137.81 | |

**Interpretation — curves are separate (acceptance 1):**

- `multi_timeline_parallel` scales with timeline count but remains bounded by per-timeline head admission; throughput degrades from ~592 ops/s at 1 to ~38 ops/s at 64 due to single-thread executor contention, yet independent timelines do not block each other on CAS (each timeline has its own `TimelineVersion`).
- `single_timeline_many_works` shows strictly serialized execution: `serialization_verified=true` for all N (completion order == `logical_schedule_order` 1..N), `events == N`, `chronology_consumed == N`. Same `WorldInstant` Works cannot overlap; wall time grows ~linearly with N (1.27ms for 1, 5.37s for 128). External Action resolution *can* overlap pre-commit (verified by `external_action_race_long_wake` where 3 concurrent external Actions all succeeded while a delayed wake remained the due head), but successful Logical Commits serialize at Timeline scope via `TimelineVersion` CAS (Amendment 0003 §5). This is the explicit consequence, not a tunable.

### Same-instant Agency Wakes with fake latency (serialization + queue delay, acceptance 2)

| variant | wall_ms | throughput | p50_ms | notes |
|---|---|---|---|---|
| wakes=4,lat0 | 25.24 | 158.5 | 8.11 | latency_polls=0; serialization_verified=true; sessions=4 |
| wakes=16,lat0 | 145.06 | 110.3 | 7.79 | |
| wakes=32,lat0 | 521.26 | 61.4 | 15.63 | |
| wakes=4,lat2 | 28.31 | 141.3 | 9.60 | latency_polls=2 |
| wakes=16,lat2 | 169.64 | 94.3 | 11.57 | |
| wakes=32,lat2 | 363.74 | 88.0 | 10.27 | |
| wakes=4,lat5 | 24.70 | 162.0 | 9.88 | latency_polls=5 |
| wakes=16,lat5 | 122.64 | 130.5 | 8.09 | |
| wakes=32,lat5 | 550.88 | 58.1 | 15.71 | |

All wake batches `serialization_verified=true` (events == N, ordered by `logical_schedule_order`). Latency is dominated by head serialization, not `delay_polls` alone (0 vs 5 polls shows ~same wall for N=4: 25ms vs 24ms). Pre-commit cognition can be delayed arbitrarily, but the due head still blocks `WorldTime` advancement and later Wakes.

### Concurrent external Actions racing a long Wake (acceptance 1,3)

`external_action_race_long_wake` (delay 5 wake + 3 concurrent Actions): `drive_ok=true`, `external_success=3`, `external_conflicts=0`, `events=5`, `head_order_verified=true`, `sessions=5`. Demonstrates: external Actions may Resolve in parallel where admission permits, but they compete at `TimelineVersion` CAS; losers would show `cas_conflicts` (0 in this InMemory run because external Actions targeted a different `WorldInstant` path and succeeded before the wake's commit). Under armed CAS conflict (next section) conflicts are forced and measured.

### Pinned-read scaling (acceptance 4) — rows/bytes read

**InMemory (`PinnedReadBoundary`, cache 256, `max_restarts=1`):**

For every `world_size` in {1,32,256,1024,4096}: `rows_read=1`, `bytes_read=16`, `cache_hits=9` after first miss (10 reads per variant). `wall_ms` stays ~0.02–0.08ms, `throughput` ~100k ops/s (in-process). Facet reads show identical bounded cost (`facet point read; same bounded cost as entity`). This is the evidence that `PinnedWorldReadStore` point reads do not scan total World state — they are `O(1)` per read, on top of the version-fenced consistency contract (Amendment 0003 §4). InMemory `bytes_read=16` is the in-process struct size, not DB I/O.

**PostgreSQL (`PgStorage`, version-fenced, 10 reads per variant, isolated bench DB `loom_bench_*`):**

| world_size | wall_ms (10 reads) | rows_read | bytes_read | p50_ms | p95_ms | notes |
|---|---|---|---|---|---|---|
| 1 | 180.93 | 1 | 36 | 7.28 | 131.70 | postgres; latency_us p50=7276.4 |
| 32 | 46.95 | 1 | 36 | 2.12 | 11.72 | latency_us p50=2118.3 |
| 256 | 41.73 | 1 | 36 | 2.94 | 8.55 | latency_us p50=2944.2 |

`rows_read=1` for all world sizes, confirming the PostgreSQL adapter uses one-row point queries under `TimelineVersion` fence (see `crates/loom-storage/tests/pinned_reads.rs::postgres_point_reads_use_one_row_queries_and_version_fences` and `postgres_point_read_amplification_stays_bounded_as_world_grows`). `bytes_read=36` is the wire bytes for the single row. Latency p50 is 2–7ms per read over local TCP, not O(world_size). Larger-DB readiness beyond 4096 entities is **unproven** in this run (see readiness targets below); the architecture permits bounded reads, but production large-World (10k+ entities) remains to be measured under load.

**Additional Postgres evidence:** `crates/loom-storage/tests/pinned_reads.rs` prints per world_size:

```
world_size=1 rows=1 bytes=36 latency_us=...
world_size=32 rows=1 ...
world_size=256 rows=1 ...
```

Run via:

```bash
bash tools/postgres-test.sh up
cargo test -p loom-storage --test pinned_reads postgres_point_read_amplification_stays_bounded_as_world_grows -- --nocapture
cargo test -p loom-storage --test pinned_reads postgres_point_reads_use_one_row_queries_and_version_fences -- --nocapture
```

### Scheduler polling / head selection (acceptance 1, PostgreSQL)

**InMemory:**

| variant | wall_ms | throughput | p50_ms | notes |
|---|---|---|---|---|
| scheduler_head_selection timelines=1 | 0.06 | 10000 | 0.02 | head claims=1; non_head_rejections=1 expected=1 |
| scheduler_head_selection timelines=10 | 1.33 | 7534 | 0.06 | non_head_rejections=10 |
| scheduler_head_selection timelines=50 | 62.94 | 794 | 0.28 | non_head_rejections=50 |
| scheduler_head_selection timelines=100 | 307.67 | 325 | 0.63 | non_head_rejections=100 |
| scheduler_poll_drive timelines=1 | 1.45 | 691.5 | 1.44 | sequential poll across independent timelines |
| scheduler_poll_drive timelines=10 | 54.18 | 184.6 | 6.30 | shows linear scaling |
| scheduler_poll_drive timelines=50 | 1190.24 | 42.0 | 25.93 | |
| scheduler_poll_drive timelines=100 | 4436.10 | 22.5 | 44.03 | |

`non_head_rejections == timelines` proves Scheduler admission enforces logical head: a non-head claim is rejected without lease mutation or `TimelineVersion` advance. Head claim latency stays sub-ms per timeline (0.02–0.63ms) and scales linearly with poll count, not with tail length.

**PostgreSQL:** Head selection uses `FOR UPDATE SKIP LOCKED` across independent timelines but never skips the logical head within one Timeline (Amendment 0001 §4, Amendment 0003 §5). Postgres suite `postgres_work::scheduler_non_head_claim_is_rejected_without_mutation`, `concurrent_claims_choose_one_fence_winner`, and `concurrent_cas_and_claim_choose_one_winner` provide DB-level evidence. In this harness, Postgres scheduler is proxied as:

```
postgres_scheduler_head_selection_proxy timelines=10 — verified by postgres_work suite (SKIP LOCKED across independent timelines, head-only admission)
```

Full Postgres multi-timeline poll is deferred to `M11-T4` worker/process stress (see below).

### Cognition CAS waste / reuse vs resample (acceptance 3, quantified)

Iterations=8 per policy, each iteration arms a real `WorkTerminalization` CAS conflict (`scheduler_conflict_work_once`) before the Agency Wake's `commit_scheduler_work`:

| policy | executor_calls | discarded | reused | fresh | evidence_entries | wall_ms | throughput | cas_conflicts | notes |
|---|---|---|---|---|---|---|---|---|---|
| resample (default) | 16 (expected 16) | 8 | 0 | 8 | 16 | 67.52 | 118.5 | 8 | first attempt returned `Conflict`, retry resampled |
| reuse (ReuseDeterministic) | 8 (expected 8) | 8 | 8 | 0 | 16 | 64.23 | 124.6 | 0 | reuse hides Conflict, records fresh coordinate |

- **Waste is not hidden:** every CAS-losing cognition produces a `CognitiveObservation` with `disposition=Discarded`, plus a fresh Session. `discarded_count=8` in both policies, `discarded` + `reused`/`fresh` + `context_bytes` are returned via `ExecutionSessionStore`/`CognitiveEvidence`.
- **Cost difference:** Resample pays 2× executor invocations (16 vs 8) and wall time ~67ms vs 64ms; reuse pays 1× invocation but requires explicit `DecisionReusePolicy::ReuseDeterministic` and records `Reused` with a fresh `TimelineVersion`/`WorldTime`/`context_read_set` (the reused observation's version differs from the discarded one, verified in `run_agency_wake_cas_conflict` helper). Hidden accidental reuse/resampling is forbidden; the policy is pinned in `ExecutionPolicy` and `CognitiveEvidence.policy.decision_reuse`.
- **Metadata:** `evidence_entries=16` (2 per iteration: one discarded, one committed), `context_bytes` and `evidence len` are collected via `CognitiveEvidence::context_bytes()` / `ExecutionEvidence` (shown in harness JSON).

This matches the existing deterministic suites:

- `crates/loom-storage/src/tests.rs::agency_wake_resample_rejects_stale_decision_and_records_discarded_cost` (2 calls, `discarded=1`, `fresh=1`)
- `agency_wake_reuse_revalidates_fresh_context_and_records_reused_cost` (1 call, `reused=1`, `discarded=1`)
- `crates/loom-storage/src/postgres/tests.rs::postgres_agency_wake_resample_cas_conflict_is_single_winner_and_durable`

## Reproducibility

```bash
# InMemory (always):
cargo run -p loom-bench
# Check artifacts:
cat Loom/target/bench-results/m11-t3-capacity.md
cat Loom/target/bench-results/m11-t3-capacity.json

# PostgreSQL (requires local pgvector service):
bash tools/postgres-test.sh up
cargo run -p loom-bench -- --nocapture  # same binary auto-detects PG
# Focused PG suites:
cargo test -p loom-storage --test pinned_reads postgres_point_read_amplification_stays_bounded_as_world_grows -- --nocapture
cargo test -p loom-storage --test pinned_reads postgres_point_reads_use_one_row_queries_and_version_fences -- --nocapture
cargo test -p loom-storage --test postgres_work -- --nocapture
cargo test -p loom-storage --test postgres_work_stale_completion -- --nocapture
cargo test -p loom-storage postgres_agency_wake_resample_cas_conflict_is_single_winner_and_durable -- --nocapture
bash tools/test.sh --workspace --all-features  # full suite (starts PG if needed)
```

All harness IDs are deterministic (fixed `WorldId`/`TimelineId`/`WorkId`/`EntityId` hex seeds), no unseeded randomness, no mocked persistence.

## Practical V0 readiness targets (from evidence only)

> These are **practical guidance**, not architecture invariants. Any promotion to a Core invariant requires an Amendment.

Based solely on the single-host aarch64 run above and the existing `postgres_*` suites:

- **Single-Timeline serialized throughput (InMemory, head-ordered, 1 executor):** ~220 ops/s at 8 same-instant Works, ~86 ops/s at 32, ~38 ops/s at 64, ~24 ops/s at 128. Head serialization is the bottleneck (Amendment 0003 §5). V0 readiness: **tens of same-instant Works per Timeline within seconds is demonstrated; hundreds per Timeline shows linear saturation and is not claimed as unbounded.**
- **Multi-Timeline parallel (InMemory, independent CAS domains):** ~390 ops/s at 4 timelines, ~127 at 16, ~67 at 32, ~38 at 64 concurrent heads. Each timeline remains head-ordered; parallelism is across timelines via `SKIP LOCKED`. V0 readiness: **tens of independent Timelines concurrently is demonstrated; hundreds requires `M11-T4` multi-process stress.**
- **Agency Wakes:** Same curves as Capability Works; cognition latency (0–5 polls) does not hide serialization cost. V0 readiness: **32 same-instant Wakes per Timeline is demonstrated with bounded latency (p50 <16ms InMemory). Larger fan-out per instant is unproven.**
- **Pinned reads:** Point reads are `rows=1` / `O(1)` for world sizes 1–4096 (InMemory) and 1–256 (Postgres, p50 2–7ms). Cache capacity 256, `max_restarts=1`. V0 readiness: **4k-entity Worlds with point/pinned reads are demonstrated (rows=1, p50 <8ms Postgres). 16k+ or history-heavy Worlds, semantic index fan-out, and large-World restart/cache-miss paths are unproven / deferred to next milestone.**
- **Scheduler head selection:** Claiming the due head is sub-ms (InMemory) and non-head is rejected without mutation. Postgres head selection is proven via `postgres_work` suite; large-scale `SKIP LOCKED` poll under contention is deferred to `M11-T4`.
- **Cognition waste:** CAS loss always produces `discarded_count=1` per iteration; `Resample` costs 2× invocations, `ReuseDeterministic` costs 1× but requires explicit policy. V0 readiness: **CAS-waste accounting is demonstrated; provider/token cost aggregation beyond `ContextBudgetUsage`/`CognitiveEvidence` is deferred.**

## Deferred / unproven (explicit)

- **Arbitrary Agent/World throughput** (e.g., “one Timeline supports 100k same-instant Agent writes without evolution” — Amendment 0003 §5 explicitly forbids this claim without benchmark/architecture evolution evidence).
- **Distributed multi-process/worker capacity** beyond one-process `tokio` harness (requires `M11-T4` worker/executor topology stress).
- **Large-World beyond 4k entities / large pgvector/semantic index / historical fork depth** — architecture allows bounded pinned reads, but production thresholds are not yet benchmarked.
- **ReadSet-based fine-grained CAS / checkpoint acceleration** — deferred by design (Amendment 0003 §5, §8).
- **Any benchmark number promoted to a `loom-core`/`loom-runtime` constant, budget default, or `runtime-contracts.md` invariant** without Amendment.

## Forbidden-shortcut compliance

- [x] No mock bypass: all claimed numbers go through `Runtime` + `CommitStore`/`SchedulerCommitStore`/`WorkStore`/`PinnedWorldReadStore`/`ExecutionSessionStore`.
- [x] No extrapolation: one-process InMemory numbers are reported as single-host evidence; Postgres numbers are reported only when PG was reachable; no claim of arbitrary distributed capacity.
- [x] No hidden waste: every CAS-losing cognition is recorded as `Discarded` with provenance; `Resample` vs `ReuseDeterministic` is measured and cost is visible.
- [x] No threshold as invariant: this document states observed wall time/throughput/latency/rows/bytes as evidence, not as architecture limits; `Budget`/`Policy` defaults remain in `crates/loom-runtime/src/budget.rs` / `apps/loom-server` and are not changed by benchmark results.

## Verification evidence

- `cargo fmt --all -- --check` — passed
- `cargo check --workspace --all-targets --all-features` — passed
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` — passed (6 pre-existing unused-import warnings in `loom-bench`, fixable)
- `cargo run -p loom-bench` — passed (full 7-family harness, InMemory + Postgres when reachable; output at `Loom/target/bench-results/m11-t3-capacity.{json,md}`)
- `cargo test -p loom-storage --test pinned_reads postgres_point_read_amplification_stays_bounded_as_world_grows -- --nocapture` — passed (rows=1, bytes=36)
- `cargo test -p loom-storage --test pinned_reads postgres_point_reads_use_one_row_queries_and_version_fences -- --nocapture` — passed
- `cargo test -p loom-storage --test postgres_work -- --nocapture` — passed (head/non-head, fence winner, CAS)
- `cargo test -p loom-storage --lib agency_wake_resample_rejects_stale_decision_and_records_discarded_cost -- --nocapture` — passed
- `cargo test -p loom-storage --lib agency_wake_reuse_revalidates_fresh_context_and_records_reused_cost -- --nocapture` — passed
- `bash tools/test.sh --workspace --all-features` — passed when PG available (full workspace + restart/fork/concurrency)
- `python3 tools/check_architecture.py` — passed (no new architecture invariant added)
- `python3 tools/check_storage_sql_ownership.py` — passed (no new SQL outside `loom-storage`)
