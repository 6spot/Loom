---
task: VALR-T22
issue: 327
status: in_progress
depends_on: [326]
created_at: 2026-08-29
started_at: 2026-08-30
completed_at:
completion_pr:
merge_sha:
architecture_decision_blocker: false
---

# VALR-T22 — Current-main V0 certification manifest

## Candidate and evidence discipline

The only production candidate for this refresh is main merge `02c55a6b5c34f227abfcb732a21bf6c390e22578` from PR #393.

PR #393 exact head `91e162105936bc1be9743ea0bc7f3dd1423a5143` and the final merge have the identical Git tree `71bb8da37f55cc5b1bb4c8ed0f004f47a4ebf00e`. CI run `33269628735` therefore validates the exact production tree. Both required jobs completed successfully: full Rust/security/architecture/workspace-test/rustdoc coverage and the complete PostgreSQL 18 persistence contract.

This manifest does not inherit a Pass from the superseded `103a75e96cd9f7b9e495a39bb6608316c47b76e6` candidate. Historical 38/2 evidence remains historical.

For CV-028 and CV-029, controlled Runtime/ProjectionStore/BlobStore operations are setup or fault drivers only. Their capability results are observed through the formal `LoomClient` read boundary introduced under Architecture Amendment 0004 and merged in PR #393. They remain outside the generic production `--all` registry because generic execution has no authority to manufacture projection delete/rebuild or blob corruption fixtures.

Status semantics:

- `ready` means the named public/controlled evidence exists on the current candidate and the required command is expected to execute it.
- `gap` means required trusted evidence is absent. This refreshed manifest contains no capability gap.
- `intentionally non-Validator-covered` is reserved for static/core governance contracts with no CV identity.

## 1. World birth / Binding / Runtime Revision

| Capability | Canonical architecture / task | Validator CV and exact test | Core/internal test evidence | PG18 contract / live requirement | Restart / persistence requirement | Required CI command / job | Status and reason | Historical reference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| World birth | World Runtime; T08 | CV-001; `apps/loom-validator/tests/lifecycle.rs` | Runtime/Storage birth contracts | Repository-managed PostgreSQL path executes in the suite | Atomic birth and immediate public readability | `bash tools/test.sh -p loom-validator --test lifecycle -- --test-threads=1` | `ready` — PR #393 exact-tree CI passed the lifecycle suite | older candidates are non-current |
| Partial Binding and missing active Revision fail closed | World Runtime; T08; T10 | CV-010..CV-011; `apps/loom-validator/tests/runtime_authority.rs` | Runtime authority tests | PostgreSQL live evidence is not mandatory for these negative paths | Rejection must not rewrite Binding or manufacture Revision | `bash tools/test.sh -p loom-validator --test runtime_authority -- --test-threads=1` | `ready` — current authority suite passed | older candidates are non-current |
| Binding immutability and Runtime Revision evolution | World Runtime; T08; T10 | CV-012..CV-014; `apps/loom-validator/tests/world_binding.rs` | Runtime Revision and binding contracts | Current suite includes controlled persistent coverage where applicable | Later revision cannot rewrite existing Binding/history | `bash tools/test.sh -p loom-validator --test world_binding -- --test-threads=1` | `ready` — current world-binding suite passed | older candidates are non-current |

## 2. Action / Ingress / Event / Facet / History

| Capability | Canonical architecture / task | Validator CV and exact test | Core/internal test evidence | PG18 contract / live requirement | Restart / persistence requirement | Required CI command / job | Status and reason | Historical reference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Action commit produces authoritative Event/Facet/History | Runtime Contracts; T08 | CV-002; `apps/loom-validator/tests/lifecycle.rs` | Effect/commit contracts | Repository-managed PostgreSQL path executes in the suite | Public truth is read after commit | `bash tools/test.sh -p loom-validator --test lifecycle -- --test-threads=1` | `ready` — current lifecycle suite passed | older candidates are non-current |
| Action and durable Ingress semantics | Runtime Contracts; T08; T11 | CV-015..CV-017; `apps/loom-validator/tests/action_ingress.rs` | Ingress idempotency/recovery contracts | Controlled PostgreSQL restart evidence is exercised by the suite | Retry/restart must not create false authoritative mutation | `bash tools/test.sh -p loom-validator --test action_ingress -- --test-threads=1` | `ready` — current action/ingress suite passed | older candidates are non-current |

## 3. Scheduler / durable Work / fencing / restart

| Capability | Canonical architecture / task | Validator CV and exact test | Core/internal test evidence | PG18 contract / live requirement | Restart / persistence requirement | Required CI command / job | Status and reason | Historical reference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Durable lifecycle restart/reopen | World Runtime; T08 | CV-003..CV-004; `apps/loom-validator/tests/lifecycle.rs` | PostgreSQL restart/resume contract | Current lifecycle suite exercises the controlled PG path | **Required:** true boundary rebuild, not reconnect-only | `bash tools/test.sh -p loom-validator --test lifecycle -- --test-threads=1` | `ready` — lifecycle and restart evidence passed | older candidates are non-current |
| Logical-head order, stale fence, independent Timelines | World Runtime; T08; T12 | CV-018..CV-020; `apps/loom-validator/tests/scheduler.rs` | Work/CAS/fence contracts | Controlled PostgreSQL 18 paths execute in the suite | Stale workers cannot overwrite the authoritative winner | `bash tools/test.sh -p loom-validator --test scheduler -- --test-threads=1` | `ready` — current scheduler suite passed | older candidates are non-current |

## 4. World Time / Chronology / Reaction

| Capability | Canonical architecture / task | Validator CV and exact test | Core/internal test evidence | PG18 contract / live requirement | Restart / persistence requirement | Required CI command / job | Status and reason | Historical reference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| World Time, chronology reconstruction and reaction atomicity | World Runtime; T08; T13 | CV-021..CV-024; `apps/loom-validator/tests/world_time.rs` | Logical replay and atomic-commit contracts | Controlled PostgreSQL 18 paths execute where required | Required restart paths reconstruct identical logical state | `bash tools/test.sh -p loom-validator --test world_time -- --test-threads=1` | `ready` — current world-time suite passed | older candidates are non-current |

## 5. Query / Catalog / semantic / blob / pinned reads

| Capability | Canonical architecture / task | Validator CV and exact test | Core/internal test evidence | PG18 contract / live requirement | Restart / persistence requirement | Required CI command / job | Status and reason | Historical reference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| History, causal isolation and world-scoped Catalog | Core/Runtime Contracts; T08; T14 | CV-025..CV-027; `apps/loom-validator/tests/query_catalog.rs` | Runtime query/causal contracts | PostgreSQL coverage is supplementary under T08 | Sibling/world authority remains isolated | `bash tools/test.sh -p loom-validator --test query_catalog -- --test-threads=1` | `ready` — current query/catalog suite passed | older candidates are non-current |
| Derived semantic projection, exact blob reference, pinned read | Implementation; Amendment 0003; Amendment 0004; T08; T15; T27 | CV-028..CV-030; `apps/loom-validator/tests/semantic_blob.rs`; CV-028 exact tests `cv028_projection_rebuild_delete_preserves_public_world_truth_in_memory`, `cv028_projection_rebuild_delete_preserves_public_world_truth_on_pg18`; CV-029 exact tests `cv029_blob_failures_preserve_public_facet_and_history_in_memory`, `cv029_blob_failures_preserve_public_facet_and_history_on_pg18` | Runtime M7 semantic/blob/pinned-read contracts are complementary only | Current controlled suite executed both InMemory and PostgreSQL 18 CV-028/CV-029 paths; T20 generic registry is not used as their evidence source | Projection/blob fixture mutation is test-only; all acceptance observations use LoomClient and unchanged public World truth | `bash tools/test.sh -p loom-validator --test semantic_blob -- --test-threads=1` | `ready` — PR #393 CI run `33269628735` executed `semantic_blob` 11/11 with formal LoomClient reads; no internal hit/blob read is promoted to Validator evidence | pre-Amendment 0004 gap evidence is historical only |

## 6. Replay / fork / isolation

| Capability | Canonical architecture / task | Validator CV and exact test | Core/internal test evidence | PG18 contract / live requirement | Restart / persistence requirement | Required CI command / job | Status and reason | Historical reference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Replay, fork and branch isolation | Core/World Runtime; T08 | CV-005..CV-009; `apps/loom-validator/tests/replay_fork.rs` | Storage/runtime replay contracts | Live PostgreSQL 18 path executes in repository CI | Fork/replay must preserve source truth and isolate branches | `bash tools/test.sh -p loom-validator --test replay_fork -- --test-threads=1` | `ready` — current replay/fork suite passed | older candidates are non-current |

## 7. Runtime Revision / Session / provenance

| Capability | Canonical architecture / task | Validator CV and exact test | Core/internal test evidence | PG18 contract / live requirement | Restart / persistence requirement | Required CI command / job | Status and reason | Historical reference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Event → Session → Revision and execution provenance | Evolution/Runtime Contracts; T08; T16 | CV-031..CV-033; `apps/loom-validator/tests/provenance.rs` | Runtime provenance contracts | Current controlled PostgreSQL restart paths execute | Restart/activation cannot rewrite prior provenance | `bash tools/test.sh -p loom-validator --test provenance -- --test-threads=1` | `ready` — current provenance suite passed | older candidates are non-current |

## 8. Agency

| Capability | Canonical architecture / task | Validator CV and exact test | Core/internal test evidence | PG18 contract / live requirement | Restart / persistence requirement | Required CI command / job | Status and reason | Historical reference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NoAction, Act, semantic rejection and CAS-loser provenance | Amendment 0003; T08; T17 | CV-034..CV-037; `apps/loom-validator/tests/agency.rs` | Cognitive/Action/Work authority contracts | T08 does not require PG18 for these controlled Agency scenarios | Test-only driver may produce decisions; public truth is observed through LoomClient | `bash tools/test.sh -p loom-validator --test agency -- --test-threads=1` | `ready` — current controlled Agency suite passed without adding production execution authority | older candidates are non-current |

## 9. Change feed / SSE

| Capability | Canonical architecture / task | Validator CV and exact test | Core/internal test evidence | PG18 contract / live requirement | Restart / persistence requirement | Required CI command / job | Status and reason | Historical reference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Change Feed/SSE observation, resume and dedup | Runtime Contracts; T08; T18 | CV-038..CV-040; `apps/loom-validator/tests/change_feed.rs` | Client/change-feed contracts | Controlled PostgreSQL restart coverage executes where required | Transport duplication cannot become World duplication | `bash tools/test.sh -p loom-validator --test change_feed -- --test-threads=1` | `ready` — current change-feed suite passed | older candidates are non-current |

## 10. Static architecture / dependency / security / build health

| Capability | Canonical architecture / task | Validator CV and exact test | Core/internal test evidence | PG18 contract / live requirement | Restart / persistence requirement | Required CI command / job | Status and reason | Historical reference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Formal client/API and architecture boundary | Governance; Implementation | No separate public Validator CV; static public-consumer contract | `python3 tools/check_architecture.py` and workspace API/client/CLI tests | Not a separate capability row | Not applicable | `cargo test -p loom-validator --lib --all-features -- --nocapture` | `intentionally non-Validator-covered` — static transport/architecture contract, while all CVs use their named evidence | older candidates are non-current |
| Aggregate repository health | CI policy | No separate public Validator CV; aggregate build gate | cargo-deny, fmt, check, strict Clippy, workspace tests, rustdoc, PostgreSQL 18 persistence contract | PostgreSQL 18 job is mandatory for the candidate | Current candidate must keep both required CI jobs green | `cargo test -p loom-validator --lib --all-features -- --nocapture` | `ready` — PR #393 exact-tree CI run `33269628735` completed both required jobs successfully | older aggregate failures are non-current |

## Current status summary

- Production candidate: `02c55a6b5c34f227abfcb732a21bf6c390e22578`.
- Candidate tree: `71bb8da37f55cc5b1bb4c8ed0f004f47a4ebf00e`.
- Exact-tree implementation head: `91e162105936bc1be9743ea0bc7f3dd1423a5143`.
- Exact-tree CI: run `33269628735`, Rust checks success, PostgreSQL 18 persistence contract success.
- Public Validator CV set: exactly CV-001 through CV-040, duplicate-free.
- Capability status: **40 ready / 0 gap**.
- CV-028/CV-029 evidence source: controlled `semantic_blob` tests with formal LoomClient observations under Amendment 0004; 11/11 semantic/blob tests passed in the full workspace run, including InMemory and PostgreSQL 18 controlled paths.
- Final certification decision is not made here. T24 must consume this manifest from merged `main`, execute its fail-closed certification gate, and T25 may publish a green certificate only if T24 reports all 40 Pass with `gate_passes=true`.
