---
task: M11-T5
issue: 197
status: in_review
depends_on: [193, 194, 195, 196]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M11-T5 — Hardening/capacity final gate

Exercise under/exact/over limits, property/fault suites, multi-worker/process load, same-Timeline head-of-line load, same-instant delayed Agency Wakes/CAS conflicts, kill/restart, dependency/security and final Linux CI.

## Assertions
- [x] Over-limit paths never partially mutate authority.
- [x] Retry/chronology/resource exits are bounded.
- [x] Stale claim/CAS/Session/Ingress crash windows remain safe.
- [x] Single-Timeline vs multi-Timeline performance documented separately.
- [x] Cognition conflict waste/reuse-resample visible.
- [x] No unsupported arbitrary-scale claim remains.
- [x] Required CI is Ubuntu/Linux and filtering never skips relevant correctness gates.

## Verification evidence
### Revision and environment

Evidence below was collected from `010571b943d9be60b2892eaae15cfd97909dde14`
(`ME-235`, current `main`) on 2026-08-25 UTC. Local execution was Linux
aarch64 with Rust `1.97.1`; PostgreSQL was the repository-managed
`pgvector/pgvector:0.8.6-pg18` service at `127.0.0.1:15432`.

The PostgreSQL fixture was started with:

```text
bash tools/postgres-test.sh up
```

When rerunning tests after a previous local run, fixed-ID unit fixtures may
need a fresh test-only volume before `up`:

```text
docker compose --project-name loom -f compose.test-db.yaml down -v
bash tools/postgres-test.sh up
```

The volume is only the repository's test database; no application data is
stored there.

The first full local run against a reused volume hit the expected fixed-fixture
collision (`loom_world` UUID `...0101` already existed). After the test-only
volume was recreated with the commands above, the complete workspace run passed;
the clean-volume prerequisite is therefore part of the reproduction record.

### Resource, property and fault gates

The under/exact/over and bounded-exit scenarios passed:

```text
cargo test -p loom-runtime --lib budget -- --nocapture
# 7 passed: action/event/work payloads, resolution counts, provenance and entropy bounds
cargo test -p loom-boundary --lib limit -- --nocapture
# 2 passed: JSON body under/exact/over and impossible transport combinations
cargo test -p loom-boundary --lib oversized_body_is_rejected_before_api_dispatch -- --nocapture
# 1 passed: body rejection precedes API dispatch
cargo test -p loom-composition-tests --test subresolution budget -- --nocapture
# 3 passed: depth, child-count and aggregate resolution budgets
cargo test -p loom-composition-tests --test entropy_finish budget -- --nocapture
# 3 passed: action/work/template budget failures retain prior entropy and finish safely
```

The deterministic property suite passed all 11 tests with the checked-in
seed. The command printed the reproducible decimal seed
`5553255009025919013`:

```text
LOOM_PROP_SEED=0x4d11200220260825 cargo test -p loom-runtime --lib property_fault_security -- --nocapture
# 11 passed; 0 failed
```

The InMemory storage fault/CAS/recovery suite passed 57 tests, including
`staged_commit_does_not_expose_event_before_work_failure`,
`stale_cas_leaves_event_state_and_work_unchanged`,
`ingress_finalization_crash_recovers_without_repeating_authority_mutation`,
`ingress_unknown_outcome_retries_reconciliation_without_dispatching_again`,
`concurrent_claims_choose_one_fence_winner`, the Agency Wake resample/reuse
tests, and chronology exhaustion:

```text
cargo test -p loom-storage --lib -- --nocapture
# 57 passed; 0 failed
```

### Capacity and topology evidence

The real Runtime/Storage/Session benchmark harness passed and wrote the
machine-readable and Markdown artifacts under `target/bench-results/`:

```text
cargo run -p loom-bench
```

The run recorded separate curves; these are measured observations, not
semantic limits:

| scenario | measured range | authority assertion |
|---|---:|---|
| `multi_timeline_parallel` | 1/4/16/32/64 timelines; 608.6 → 91.7 ops/s | independent CAS domains; no cross-Timeline mutation |
| `single_timeline_many_works` | 1/8/32/64/128 works; 893.0 → 65.5 ops/s | `serialization_verified=true`; events and chronology consumed equal N |
| `agency_wakes_same_instant` | 4/16/32 wakes × delay polls 0/2/5 | every variant completed N/N and remained head ordered |
| `external_action_race_long_wake` | 3 Actions vs one delayed Wake | `external_success=3`, `events=5`, `head_order_verified=true` |
| `pinned_reads_scaling` | InMemory world sizes 1–4096 | rows=1, bytes=16, cache hits=9 per 10 reads |
| `postgres_pinned_reads` | PostgreSQL world sizes 1/32/256 | rows=1, bytes=36; p50 1.27–1.61 ms |
| `scheduler_head_selection` | 1/10/50/100 Timelines | non-head rejections exactly equaled Timelines; no mutation |

The cognition conflict run made waste and policy visible: with 8 induced
conflicts, `resample` recorded 16 executor calls, 8 discarded observations,
8 fresh decisions and 8 CAS conflicts; explicit `reuse` recorded 8 executor
calls, 8 discarded and 8 reused observations. No reuse was inferred or hidden.

The benchmark only supports the measured dataset sizes above. Arbitrary-scale,
100k same-instant Timeline, 16k+ World, or distributed throughput claims remain
unproven and are not made here.

The PostgreSQL worker/process topology and restart/fence matrix passed inside
the full workspace run, including the four-worker isolated Session/provenance
scenario `postgres_18_worker_topology_keeps_sessions_and_provenance_isolated`,
independent Timeline concurrency, stale-fence completion, durable scheduler
budget, ingress reopen/recovery, Runtime reconstruction, fork-after-restart,
and commit/CAS rollback tests. The repository's process-fault model is the
documented boundary of dropping a worker-owned Runtime/Storage handle and
reopening it; no separate OS `SIGKILL` black-box test is claimed.

### Dependency, security and local Linux gates

All local policy and CI-equivalent gates passed:

```text
cargo deny check advisories bans licenses sources
# cargo-deny 0.18.9; all four checks passed
python3 tools/check_architecture.py
# passed
python3 tools/check_storage_sql_ownership.py
# passed
docker compose -f compose.test-db.yaml config --quiet
# passed
docker compose -f compose.yaml config --quiet
# passed
cargo fmt --all -- --check
# passed
cargo check --workspace --all-targets --all-features
# passed
cargo clippy --workspace --all-targets --all-features -- -D warnings
# passed
bash tools/test.sh --workspace --all-features
# passed on a clean test volume
RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps
# passed
```

The clean full workspace run included all PostgreSQL contract suites: schema,
lifecycle/template birth, vertical/read parity, commit/CAS, durable Work,
stale Work fence, restart/resume, revision, ingress, fork, pinned reads and
semantic projection. The final counts included 69 Runtime tests, 57 Storage
unit tests, 12 PostgreSQL Work tests, 1 stale-completion test, 4 pinned-read
tests and all other workspace/integration/doc tests with zero failures.

The authoritative GitHub run for this exact revision also passed:

```text
gh run list --workflow ci.yml --commit 010571b943d9be60b2892eaae15cfd97909dde14 --limit 10
# run 32793033132: completed / success
gh run view 32793033132 --json jobs,workflowName,headSha,status,conclusion,url
# Rust checks: success; PostgreSQL 18 persistence contract: success
```

Both CI jobs ran on `ubuntu-latest`; the workflow has no macOS job. Its positive
path filters include workflow files, Rust/Cargo metadata, SQL/migrations,
tests, tools, Compose/Docker and capability paths, while docs/task-only changes
remain outside the expensive Rust path set. The local `rg` audit was:

```text
rg -n '^\\s*runs-on:|macos|ubuntu|paths:|\\.rs|Cargo|tools' .github/workflows/ci.yml
# only ubuntu-latest runs-on entries; no macos match; both push/PR path sets present
```
