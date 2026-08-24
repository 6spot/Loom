---
task: M11-T1
issue: 193
status: in_review
depends_on: [192]
created_at: 2026-08-22
started_at: 2026-08-24
completed_at:
completion_pr:
merge_sha:
---
# M11-T1 — Bounded resource policies

- Inventory/configure limits across Action/Event/Work payloads, Resolution/subresolution, Reaction scheduling, chronology, retrieval/history/causal queries, Agent context/cognition, provenance, Ingress, HTTP/SSE and worker concurrency.
- Runtime enforces semantic/execution bounds independently of Boundary; Boundary rejects oversized transport early where practical.
- Server validates unsafe/impossible config and can expose non-secret effective policy.
- Under/exact/over tests prove typed failure and no partial authority mutation.

## Limit inventory

All values below are finite deployment policy. `ResolutionBudget::unlimited()`
is reserved for explicit tests and internal diagnostics; it is not a server
default. Runtime checks remain active for in-process API calls even when the
Boundary has already accepted the transport request.

| amplification path | owner | config key / finite default | enforcement point |
| --- | --- | --- | --- |
| Action input bytes | `loom-runtime` | `LOOM_RUNTIME_MAX_ACTION_PAYLOAD_BYTES` / 262144 | Action validation before schema/handler dispatch |
| Event payload bytes | `loom-runtime` | `LOOM_RUNTIME_MAX_EVENT_PAYLOAD_BYTES` / 262144 | Resolution budget validation before commit |
| Work payload bytes | `loom-runtime` | `LOOM_RUNTIME_MAX_WORK_PAYLOAD_BYTES` / 262144 | Resolution budget validation before commit |
| Resolution Events / Effects / WorkMutations | `loom-runtime` | `LOOM_RUNTIME_MAX_EVENTS` / 256; `...MAX_EFFECTS` / 1024; `...MAX_WORK_MUTATIONS` / 256 | `ResolutionBudget::check` before `ValidatedResolution` |
| Subresolution depth / count | `loom-runtime` | `LOOM_RUNTIME_MAX_SUBRESOLUTION_DEPTH` / 8; `...MAX_SUBRESOLUTION_COUNT` / 64 | child dispatch accounting and root resolution validation |
| Reaction scheduling fan-out | `loom-runtime` | `LOOM_RUNTIME_MAX_REACTION_SCHEDULES` / 256 | reaction expansion before each generated Work item |
| Chronology completions at one WorldInstant | `loom-runtime` | `LOOM_RUNTIME_MAX_CHRONOLOGY_COMPLETIONS` / 1024 | `ChronologyBudgetPolicy` in Timeline drive/commit |
| Semantic query count / results / bytes / depth / filters | `loom-runtime` | `...MAX_SEMANTIC_QUERIES` / 64; `...RESULTS` / 1024; `...RESULT_BYTES` / 1048576; `...DEPTH` / 32; `...FILTERS` / 1 | Runtime semantic mediation and storage adapter validation |
| Event history page | `loom-runtime` / `loom-api` | `LOOM_RUNTIME_MAX_HISTORY_PAGE_SIZE` / 1024 | Runtime `EventQuery` normalization before storage |
| Causal traversal depth / results | `loom-runtime` / `loom-api` | `LOOM_RUNTIME_MAX_CAUSAL_DEPTH` / 64; `...MAX_CAUSAL_RESULTS` / 1024 | Runtime `CausalQuery` and trajectory normalization |
| Entity/relationship trajectory limits | `loom-runtime` / `loom-api` | shared causal depth/results policy above | Runtime history traversal before storage |
| Agent context items / bytes | `loom-agency` | `ContextBudget` / 128 items, 65536 bytes | `AgentWorldViewBuilder` before context publication |
| Cognition input/output bytes | `loom-runtime` / `loom-agency` | `ContextBudget` / 65536 bytes plus Action payload / 262144 | cognition gateway context check and normal Action validation |
| Cost evidence count / bytes | `loom-runtime` | Session provenance entries / 4096; bytes / 4194304 | evidence assembly before session persistence |
| Ingress body / retry attempts | `loom-runtime` / `loom-api` | `LOOM_INGRESS_MAX_PAYLOAD_BYTES` / 524288; `LOOM_INGRESS_MAX_RETRY_ATTEMPTS` / 3 | envelope serialization before enqueue and `FailurePolicy` retry transition |
| Ingress queue capacity | `loom-server` | `LOOM_INGRESS_QUEUE_CAPACITY` / 256 | bounded Tokio channel construction |
| HTTP request body / headers / response | `loom-boundary` | `LOOM_HTTP_MAX_BODY_BYTES` / 1048576; `...HEADER_BYTES` / 16384; `...RESPONSE_BYTES` / 8388608 | request header/body extraction and response serialization |
| SSE buffer / events | `loom-boundary` | `LOOM_HTTP_MAX_SSE_BUFFER_BYTES` / 4194304; `...SSE_EVENTS` / 1000 | SSE page/frame serialization before response |
| HTTP concurrent requests | `loom-boundary` | `LOOM_HTTP_MAX_CONCURRENT_REQUESTS` / 128 | `ConcurrencyLimitLayer` |
| Worker lease / retry / scheduler poll / recovery batch | `apps/loom-server` | `LOOM_WORKER_LEASE_MS` / 30000; `...RETRY_BACKOFF_MS` / 1000; `...SCHEDULER_POLL_LIMIT` / 1; `...RECOVERY_BATCH_SIZE` / 256 | `WorkerConfig`, scheduler `run_bounded`, and Ingress recovery scan |
| Session ReadSet / ExecutionEvidence entries and bytes | `loom-runtime` | `LOOM_RUNTIME_MAX_SESSION_PROVENANCE_ENTRIES` / 4096; `...BYTES` / 4194304 | Runtime session finish and cognitive gateway; semantic/entropy provenance included |

`ServerConfig::from_env` rejects non-positive values, public API bounds that
cannot be honored, and impossible transport combinations (header > body,
response < body, SSE buffer > response, or SSE events above the public Change
Feed bound). `ServerConfig` debug output contains effective non-secret limits
but redacts the database URL.

## Forbidden
No HTTP-only protection, unbounded production recursive/query defaults, silent truncation without cursor contract, or deployment thresholds in Core.

## Acceptance
- [ ] Every amplification path has owner/config/enforcement.
- [ ] Over-limit semantic execution cannot partially commit.
- [ ] Runtime/Boundary independent limit tests pass.
- [ ] Invalid server config fails startup.
- [ ] Standard/integration gates pass.

## Verification evidence

- `cargo fmt --all -- --check`
- `cargo check --workspace --all-targets --all-features`
- `cargo test --workspace --all-features` (all workspace, integration, PostgreSQL and doc tests passed)
- `cargo clippy --workspace --all-targets --all-features -- -D warnings`
- `python3 tools/check_architecture.py`
- Boundary body under/exact/over and impossible-combination tests
- Runtime Event payload exact/over and atomic Timeline/World commit tests
- Runtime and Boundary execute their own limits; Boundary acceptance does not
  disable Runtime policy checks
