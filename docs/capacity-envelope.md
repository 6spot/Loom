# Loom V0 Capacity Envelope — measured evidence (M11)

> All numbers below are **observed evidence** from the benchmark harness on the recorded environment and dataset sizes in `docs/tasks/m11/t3-capacity-benchmarks.md`. They are not semantic architecture limits, not invariants, and must not be promoted to a Core/Runtime contract without an explicit Architecture Amendment. Production readiness targets are derived only from this evidence; larger-scale claims are marked **unproven / deferred**.

## Methodology

**Harness:** `crates/loom-bench` (`crates/loom-bench/src/lib.rs`, `crates/loom-bench/src/main.rs`) drives the real `Runtime` + `InMemoryStore` (and `PgStorage` when PostgreSQL is reachable) through the standard `CommitStore`/`WorkStore`/`SchedulerCommitStore`/`PinnedWorldReadStore`/`ExecutionSessionStore` ports, `Runtime::drive_timeline`, `ActionService::invoke`, `ExecutionPolicy`/`DecisionReusePolicy` and `PinnedReadBoundary`. No mock bypass. Deterministic `DeterministicCognitiveExecutor` with configurable `delay_polls` simulates cognition; `inject_scheduler_conflict_once_for_test` arms a real `TimelineVersion` CAS conflict via `WorkTerminalization` authority.

**Reproducibility:**

```bash
# InMemory always:
cargo run -p loom-bench
cat target/bench-results/m11-t3-capacity.md
cat target/bench-results/m11-t3-capacity.json

# PostgreSQL (requires local pgvector service):
bash tools/postgres-test.sh up
cargo run -p loom-bench -- --nocapture  # same binary auto-detects PG
# Focused PG suites:
cargo test -p loom-storage --test pinned_reads postgres_point_read_amplification_stays_bounded_as_world_grows -- --nocapture
cargo test -p loom-storage --test pinned_reads postgres_point_reads_use_one_row_queries_and_version_fences -- --nocapture
cargo test -p loom-storage --test postgres_work -- --nocapture
bash tools/test.sh --workspace --all-features
```

**Environment (`2026-08-24` run):** `rustc 1.97.1`, `Linux 6.12.0-201.74.2.2.el9uek.aarch64 aarch64`, `MemTotal 23496384 kB`, `postgres pgvector/pgvector:0.8.6-pg18` at `127.0.0.1:15432`, `git_sha 830cf38` pre-M11-T3.

## 1. Single-Timeline vs Multi-Timeline

Scheduling on one Timeline is strictly ordered `(effective_due_world_time, logical_schedule_order)`; successful Logical Commits serialize at Timeline scope via `TimelineVersion` CAS (Amendment 0003 §5).

### Multi-Timeline independent CAS domains (concurrent via `futures::join_all`)

| variant | dataset | wall_ms | throughput ops/s | p50_ms | notes |
| --- | --- | --- | --- | --- | --- |
| timelines=1 | 1 | 1.69 | 591.7 | 1.67 | one Immediate Work at `WorldInstant(0)` order 1 per timeline |
| timelines=4 | 4 | 10.21 | 391.6 | 1.64 |  |
| timelines=16 | 16 | 125.91 | 127.1 | 7.47 |  |
| timelines=32 | 32 | 479.40 | 66.7 | 14.16 |  |
| timelines=64 | 64 | 1696.20 | 37.7 | 18.24 |  |

### Single-Timeline many same-instant Works (sequential `drive_timeline` loop)

| variant | dataset | wall_ms | throughput ops/s | p50_ms | notes |
| --- | --- | --- | --- | --- | --- |
| works=1 | 1 | 1.27 | 785.4 | 1.27 | `serialization_verified=true`, `events=1`, `chronology_consumed=1` |
| works=8 | 8 | 36.55 | 218.9 | 6.37 |  |
| works=32 | 32 | 371.45 | 86.1 | 11.46 |  |
| works=64 | 64 | 1701.37 | 37.6 | 24.20 |  |
| works=128 | 128 | 5373.70 | 23.8 | 33.85 |  |

**Interpretation:** `serialization_verified=true` for all N (completion order == `logical_schedule_order` 1..N). Same `WorldInstant` Works cannot overlap; wall time grows ~linearly with N (e.g. 1 Works at ~1.3 ms, 128 at ~5.4 s). Independent Timelines do not block each other on CAS but share single-thread executor contention, degrading throughput. External Action resolution may overlap pre-commit, but losers would show `cas_conflicts` (verified by the `external_action_race_long_wake` scenario where 3 concurrent external Actions succeeded at `external Success=3` alongside a delayed wake at `serialization_verified=true` — they raced before the wake's CAS).

## 2. Same-instant Agency Wakes with fake latency

| variant | wall_ms | throughput | p50_ms | notes |
| --- | --- | --- | --- | --- |
| wakes=4,lat0 | 25.24 | 158.5 | 8.11 | `serialization_verified=true`, `sessions=N` |
| wakes=16,lat0 | 145.06 | 110.3 | 7.79 |  |
| wakes=32,lat0 | 521.26 | 61.4 | 15.63 |  |
| wakes=4,lat2 | 28.31 | 141.3 | 9.60 | `delay_polls=2` |
| wakes=16,lat2 | 169.64 | 94.3 | 11.57 |  |
| wakes=32,lat2 | 363.74 | 88.0 | 10.27 |  |
| wakes=4,lat5 | 24.70 | 162.0 | 9.88 | `delay_polls=5` |
| wakes=16,lat5 | 122.64 | 130.5 | 8.09 |  |
| wakes=32,lat5 | 550.88 | 58.1 | 15.71 |  |

Latency is dominated by head serialization, not `delay_polls` alone (0 vs 5 polls at N=4: ~25 ms vs ~25 ms). Cognition may delay arbitrarily pre-commit, but the due head still blocks `WorldTime` advancement and later Wakes.

## 3. Pinned-read scaling — rows/bytes read (O(1) per point read)

**InMemory (`PinnedReadBoundary`, cache 256, `max_restarts=1`, 10 reads per variant):**

For every `world_size` in {1, 32, 256, 1024, 4096}: `rows_read=1`, `bytes_read=16`, `cache_hits=9` after first miss, `wall_ms ~0.02–0.08 ms` (`~100k ops/s`). Facet reads show identical bounded cost. This is evidence that `PinnedWorldReadStore` point reads do not scan total World state — they are `O(1)` per read on top of the version-fenced consistency contract (Amendment 0003 §4). InMemory `bytes_read=16` is the in-process struct size, not DB I/O.

**PostgreSQL (`PgStorage`, version-fenced, 10 reads per variant, isolated bench DB `loom_bench_*`):**

| world_size | wall_ms (10 reads) | rows_read | bytes_read | p50_ms | p95_ms |
| --- | --- | --- | --- | --- | --- |
| 1 | 180.93 | 1 | 36 | 7.28 | 131.70 |
| 32 | 46.95 | 1 | 36 | 2.12 | 11.72 |
| 256 | 41.73 | 1 | 36 | 2.94 | 8.55 |

`rows_read=1, bytes=36` for all world sizes, confirming the PostgreSQL adapter uses one-row point queries under `TimelineVersion` fence (`crates/loom-storage/tests/pinned_reads.rs::postgres_point_reads_use_one_row_queries_and_version_fences`, `postgres_point_read_amplification_stays_bounded_as_world_grows`). Latency p50 is 2–7 ms per read over local TCP, not O(world_size). Larger-DB readiness beyond 4096 entities is **unproven** in this run; the architecture permits bounded reads but production large-World (10k+ entities) remains to be measured under load.

## 4. Scheduler polling / head selection

| variant | wall_ms | throughput | p50_ms | notes |
| --- | --- | --- | --- | --- |
| head_selection timelines=1 | 0.06 | 10000 | 0.02 | `head_claims=1`, `non_head_rejections=1 expected=1` |
| head_selection timelines=10 | 1.33 | 7534 | 0.06 | `non_head_rejections=10` |
| head_selection timelines=50 | 62.94 | 794 | 0.28 | `non_head_rejections=50` |
| head_selection timelines=100 | 307.67 | 325 | 0.63 | `non_head_rejections=100` |
| poll_drive timelines=1 | 1.45 | 691.5 | 1.44 | sequential poll across independent timelines |
| poll_drive timelines=10 | 54.18 | 184.6 | 6.30 |  |
| poll_drive timelines=50 | 1190.24 | 42.0 | 25.93 |  |
| poll_drive timelines=100 | 4436.10 | 22.5 | 44.03 |  |

`non_head_rejections == timelines` proves Scheduler admission enforces the logical head: a non-head claim is rejected without lease mutation or `TimelineVersion` advance (head `claim latency ~0.02–0.63 ms`). PostgreSQL evidence: `postgres_work::scheduler_non_head_claim_is_rejected_without_mutation`, `concurrent_claims_choose_one_fence_winner`; head selection uses `FOR UPDATE SKIP LOCKED` only across independent timelines but never within one Timeline.

## 5. Cognition CAS waste — Resample vs Reuse

Iterations=8 per policy, each iteration arms a real `WorkTerminalization` CAS conflict (`scheduler_conflict_work_once`) before the Agency Wake's `commit_scheduler_work`:

| policy | executor_calls | discarded | reused | fresh | evidence_entries | wall_ms | throughput | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `Resample` (default) | 16 (expected 16) | 8 | 0 | 8 | 16 | 67.52 | 118.5 | second attempt resampled; `cas_conflicts=8` |
| `ReuseDeterministic` | 8 (expected 8) | 8 | 8 | 0 | 16 | 64.23 | 124.6 | `Reused` records fresh `TimelineVersion`/`WorldTime`/`context_read_set` |

`discarded_count=8` in both policies demonstrates that waste is not hidden: every CAS-losing cognition produces a `CognitiveObservation` with `disposition=Discarded` retained in Session provenance. `Resample` pays 2× executor invocations; `ReuseDeterministic` pays 1× but requires an explicit `DecisionReusePolicy::ReuseDeterministic` and revalidated deterministic decision (verified in `run_agency_wake_cas_conflict`). Provenance verifies `evidence_entries=16` (2 per iteration). Suicide suite references: `loom-storage/src/tests.rs::agency_wake_resample_rejects_stale_decision_and_records_discarded_cost` (2 calls, `discarded=1`, `fresh=1`), `agency_wake_reuse_revalidates_fresh_context_and_records_reused_cost` (1 call, `reused=1`, `discarded=1`).

## 6. Readiness targets and deferrals

| Claim | Status |
| --- | --- |
| Single-Timeline head-ordered serialization correctness | **Measured and verified** (see §1 `serialization_verified`, logical journal replay tests) |
| Multi-Timeline independent CAS parallelism | **Measured** (§1 curves, `postgres_work` concurrent claims have one fence winner) |
| Pinned point-read O(1) rows/bytes not scanning World | **Measured** (§3, `rows_read=1` for 1..4096 InMemory / 1..256 PG) |
| Cognition waste quantified per policy | **Measured** (§5, both policies record discarded cost) |
| Large-World 10k+ entity production latency under load | **Unproven / deferred** — must be measured separately for 10k+ before claimed |
| Multi-threaded shared-process Runtime topology | **Deferred** — current contract is `one Linux worker process → one single-thread executor → one Runtime`; cross-timeline concurrency is via independent processes (see `docs/development/runtime-worker.md`) |
| Fine-grained `ReadSet` commit validation beyond Timeline-wide CAS | **Deferred** (Amendment 0003 §5) |
| Historical replay/fork checkpointing / snapshot acceleration | **Deferred** |
| Real vendor LLM as required V0 path | **Non-blocking / deferred** — deterministic fake is benchmark/test evidence only (`loom-bench`, `loom-agency/src/testing.rs`), not a default public composition example; a supported public deterministic fake fixture/adapter is **deferred** to `M12-T3`/T4; real adapters remain application-owned |
| macOS / large-scale production SLOs | **Not claimed** — CI required baseline is Ubuntu/Linux; macOS restoration timing is a deferred decision (`architecture/README.md` §4) |
| Numeric retry/backoff/budget defaults as invariants | **Not invariants** — they are deployment policy (`LOOM_RUNTIME_MAX_*`, `FailurePolicy`, `ChronologyBudgetPolicy`) measured but not architecture-guaranteed |

All larger-scale claims beyond the measured envelope above remain unproven until reproduced with the harness under load. Production targets must be derived only from re-measured evidence, not from architecture aspiration.

## 7. Full source

The authoritative benchmark tables, dataset sizes and reproduction commands are in `docs/tasks/m11/t3-capacity-benchmarks.md` (the task ledger owns the primary evidence). This file is a concise consumer-facing summary; if the two diverge, the task ledger's tables and `target/bench-results/m11-t3-capacity.{json,md}` are authoritative.
