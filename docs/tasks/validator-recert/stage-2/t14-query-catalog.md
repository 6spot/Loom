---
task: VALR-T14
issue: 319
status: in_progress
depends_on: [314]
created_at: 2026-08-26
started_at: 2026-08-27
completed_at:
completion_pr:
merge_sha:
---

# VALR-T14 — Validate Query/History/Causal reads + world-scoped Catalog authority

Validate public read/query behavior, branch/timeline isolation and world-scoped Catalog authority against immutable Binding + active Runtime Revision per T08 rows CV-025..CV-027. Production code and assertions use formal `loom-api`/`loom-client` surfaces; the T14-owned causal and bound-World fixtures use `loom-runtime`/`loom-storage` only for controlled setup. No central registry, core semantics, or storage implementation is changed.

## Goal

Provide validator coverage for T08 CV-025..CV-027:

- **CV-025:** history/trajectory reads return the committed path for the requested World/Timeline and do not leak sibling-fork state; ordering by `EventSeq`.
- **CV-026:** causal/query reads preserve branch/world isolation and documented ordering/identity contract via `direct_causes`/`direct_effects`/`causal_walk`/`get_event`.
- **CV-027:** world-scoped Catalog requires World's Binding plus compatible active Runtime Revision; no active revision must not silently fall back to globally available software.

Evidence must demonstrate fork/sibling isolation for representative history/trajectory/causal reads, world-scoped catalog positive case under compatible active revision, explicit no-active-revision negative case, and controlled PostgreSQL path where T08 marks read persistence evidence required (T14 rows have `PG live = No`, but controlled PG is exercised when available).

## Scope

Allowed (T09 parallel-safe boundary):

- `apps/loom-validator/src/query_catalog.rs` — dedicated production suite module (CV-025..027 descriptors + `execute_query_catalog` via public LoomApi surfaces).
- `apps/loom-validator/tests/query_catalog.rs` — dedicated integration tests + controlled fixtures (`InMemoryServer`/`PgServer` from `tests/common`).
- `apps/loom-validator/tests/query_catalog_causal_fixture.rs` — T14-owned test-only causal and bound-World setup; assertions remain on public `LoomApi` surfaces.
- `apps/loom-validator/Cargo.toml` — test-only `loom-core`/`loom-protocol` dependencies required by the local resolver fixture.
- This ledger `t14-query-catalog.md`.

Forbidden (per Leader):

- No central registry edits (`apps/loom-validator/src/registry.rs`, `src/lib.rs` `validator_registry`, CLI dispatch) — T19 owns.
- No internal catalog/storage reads from production Validator code; no `loom-runtime`/`loom-storage` direct reads in production suite.
- Do not weaken the post-M13 canonical revision authority fix.
- No core implementation changes in this leaf; no other Stage-2 suite file edits.

## Produced

### Production suite `apps/loom-validator/src/query_catalog.rs`

- Preserved `SUITE = "query_catalog"`, `CV_RANGE = "CV-025..CV-027"`, `CAPABILITY_AREA = "query-catalog"`, `suite_name()`, `owns_cv()`.
- Added stable `CV_025`, `CV_026`, `CV_027` constants.
- `descriptors() -> Vec<ScenarioDescriptor>` (3 descriptors, deterministic, non-overlapping, `query-catalog` area, `InMemory`+`PostgreSQL` backends, prerequisites per T08).
- `query_catalog_descriptors()` alias and `register_query_catalog()` for local test registries (not global).
- `execute_query_catalog(descriptor, &BackendContext) -> ScenarioResult` dispatcher with PostgreSQL prerequisite gate (`LOOM_TEST_POSTGRES_URL` presence/scheme) and live `catalog()` reachability check, matching `scenarios.rs` policy.
- `cv025`: creates World `validator.t14.cv025.*` with `neutral.counter@^0.1.0`, seeds `value=5`, forks child A and sibling B from seeded parent, increments child to `15`, verifies via `get_facet`/`list_events`/`entity_trajectory`/`inspect_timeline` ancestry, `EventSeq` ordering, and ancestor-future exclusion (parent increment to `7` does not leak to child). History isolation: parent `1`, child `2`, sibling `1`; facets `5/15/5`; trajectory matches history when participants present or `0` for neutral (accepted as non-leak). Ancestry `fork_parent_version` correct. `Pass` only when all isolation predicates hold.
- `cv026`: same fork topology plus sibling increment to `12` (parent seed `5`), verifies public history/query isolation and ordering. The T14-local causal fixture independently registers a causal-enabled resolver, commits child `E2` with `cause_event_id=ancestor E1`, proves `direct_causes(E2)==[E1]` and Causes walk visibility/identity, observes parent-qualified `direct_effects(E1)` does not reverse-discover child/sibling, then rejects a sibling reference to inaccessible `E2` without child/parent/sibling history mutation.
- `cv027`: inspects `active_runtime_revision()` via `AdminService`. If `None`, the descriptor records installed global catalog observation; the T14-local bound-World fixture creates and retains an immutable Binding while active, then observes `catalog_for_world(bound_world)` through a fresh no-active Runtime and requires `Unavailable`/`NotFound` without global fallback. If `Some`, positive case creates `W_a` (`counter` only) and `W_b` (`counter+observer`) and asserts exact public capability identity sets `{neutral.counter}` and `{neutral.counter, neutral.observer}`, both subsets of global.
- Helpers: `block_on`, `check_postgres_prerequisite`, `is_infra_unavailable`, `finding_for`, `result_pass`/`result_fail`, `new_world_template` with `WorldInstant(42)`, deterministic `entity/event` via `Uuid::new_v4()`. Uses only `loom-api`+`loom-client`+`serde_json`+`uuid`+`tokio` (production deps); no storage/runtime imports.
- Unit tests: descriptors deterministic `3` ids, `query_catalog_descriptors` alias, `owns_cv` disjoint, local registry `3` disjoint from global `11`, backend support `InMemory`+`PostgreSQL` only.

### Integration test `apps/loom-validator/tests/query_catalog.rs`

- Retained scaffold assertion: `validator_registry().len()==11`, `CV-025` unregistered, disjoint `owns_cv`.
- `common` harness (`InMemoryServer`/`PgServer`) composition via `loom-runtime`+`loom-storage`+`neutral`+`loom-boundary` router over HTTP (test-only, not production).
- `in_memory_context(scope)` and `pg_context(scope)` helpers with `BackendContext::new` + `with_backend_kind` + `with_restart_strategy` + `with_controlled_boundary_restart`.
- `cv025_history_trajectory_isolation_on_in_memory` — executes `CV-025` via `execute_query_catalog` on `InMemory` and asserts `Pass`.
- `cv026_causal_query_isolation_on_in_memory` — runs the T14-local causal fixture, then executes `CV-026` on `InMemory` and asserts `Pass`.
- `cv027_world_scoped_catalog_positive_on_in_memory` — executes `CV-027` positive path on `InMemory` and asserts `Pass`.
- `cv027_no_active_revision_is_not_permissive` — first runs the bound-World fixture (World/Binding created while active, then fresh no-active observation), verifies installed global catalog, and executes `CV-027` on `InMemoryServer::start_without_active_revision` for the descriptor no-active observation.
- `cv025_to_cv027_postgres_when_available` — for each CV, attempts `PgServer::start`; if `LOOM_TEST_POSTGRES_URL` missing, verifies `BackendHarness::PostgreSQL` reports `Prerequisite` and skips as non-`Fail`; if PG live, asserts `!is_fail` (Pass or prerequisite/unavailable, not logic Fail).
- `catalog_authority_does_not_use_global_fallback_on_controlled_in_memory` — direct `LoomClient` formal-surface check: global catalog has installed software, and exact public identity sets are `W_a={neutral.counter}` and `W_b={neutral.counter,neutral.observer}`, both subsets of global.
- All production code and assertions use public surfaces (`WorldService::create_world_from_template`, `ActionService::invoke`, `TimelineService::fork`/`inspect_timeline`, `QueryService::get_facet`, `HistoryService::list_events`/`entity_trajectory`/`get_event`/`direct_causes`/`direct_effects`/`causal_walk`, `CatalogService::catalog`/`catalog_for_world`, `AdminService::active_runtime_revision`). The local fixture uses storage/runtime traits only to compose controlled setup; it performs no raw table reads and does not alter implementation semantics.

### Ledger `t14-query-catalog.md` (this file)

Documents ownership/write scopes, T08 mapping, forbidden scopes, and verification evidence.

## Ownership / Write Scope

Disjoint primary ownership per T09 ledger:

| Leaf | Primary production file | Primary test file | CV range |
| --- | --- | --- | --- |
| T14 (#319) | `apps/loom-validator/src/query_catalog.rs` | `apps/loom-validator/tests/query_catalog.rs` | `CV-025..CV-027` |

No other `src/*.rs`, `tests/*.rs`, `src/lib.rs`, `src/registry.rs`, `src/scenarios.rs`, `tests/common/mod.rs` edited. `t08-coverage-matrix.md` and `t09-suite-scaffold.md` read-only.

## T08 Mapping

| CV | Capability | Precondition | Formal Surface | Expected Result | Evidence Classes | PG live | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CV-025 | History/trajectory positive isolation | parent seeded `5`, child fork `15`, sibling untouched | `list_events`, `entity_trajectory`, `inspect_timeline` ancestry, `get_facet` | child `2` events `15`, sibling `1`/`5`, trajectory per timeline isolated, ancestor-future excluded, ordering `EventSeq` | controlled InMemory, controlled PostgreSQL | No | T14 |
| CV-026 | Causal/query branch/world isolation | T14-local causal-enabled fixture: parent seed `E1`, child `E2` with `cause_event_id=E1`, sibling invalid reference | `direct_causes`, `causal_walk`, parent-qualified `direct_effects`, `ActionService::invoke`, `list_events` | `direct_causes(E2)==[E1]`; Causes walk sees E1 with correct identity/order; parent-qualified reverse lookup does not discover child/sibling; sibling reference is rejected with no history/EventSeq mutation | controlled InMemory fixture, controlled PostgreSQL descriptor path | No | T14 |
| CV-027 | World-scoped Catalog authority | `W_a` `{counter}`, `W_b` `{counter,observer}` under `R-comp`; bound World created while active then retained in fresh no-active fixture | `catalog`, `catalog_for_world`, `active_runtime_revision` | exact public identity sets for W_a/W_b; bound no-active World → `Unavailable`/`NotFound`, never global fallback | controlled InMemory fixture, controlled PostgreSQL descriptor path | No | T14 |

All rows marked implementable via existing `loom-api` surfaces; no new authority invented. If public API cannot distinguish branch/revision authority, leaf must stop and escalate per Stop Conditions — not triggered.

## Verification Evidence

- `cargo fmt --all -- --check` → PASS (no diff)
- `cargo check -p loom-validator --all-targets` → PASS
- `cargo clippy -p loom-validator --all-targets -- -D warnings` → PASS
- `cargo test -p loom-validator --lib` → PASS, 156 passed, 0 failed
- `cargo test -p loom-validator --test query_catalog -- --nocapture` → PASS, 7 passed, 0 failed
  - `query_catalog_suite_scaffold_is_non_registering_and_disjoint` — Pass, `validator_registry len 11`, `CV-025` unregistered, local `3`
  - `cv025_history_trajectory_isolation_on_in_memory` — Pass (history/trajectory isolation, ancestor-future)
  - `cv026_causal_query_isolation_on_in_memory` — PASS; T14-local fixture committed causal child E2→ancestor E1, verified direct causes/Causes walk identity and ordering, parent-qualified reverse lookup non-discovery, sibling rejection, and unchanged histories
  - `cv027_world_scoped_catalog_positive_on_in_memory` — Pass (catalog filtered, distinct, subset)
  - `cv027_no_active_revision_is_not_permissive` — PASS; bound World created with active revision and immutable Binding retained in fresh no-active fixture; public world-scoped catalog returned `Unavailable`/`NotFound`, global catalog remained installed
  - `catalog_authority_does_not_use_global_fallback_on_controlled_in_memory` — Pass (direct formal surface)
  - `cv025_to_cv027_postgres_when_available` — 3 Postgres prerequisite Skipped `missing LOOM_TEST_POSTGRES_URL` (not Fail) when PG not configured; would be `Pass` with live PG
- `cargo test -p loom-validator --all-targets` → not rerun as a required broad check this turn; the required T14 lib and query_catalog targets above are PASS
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json` → `valid=true` after ledger added (stage-2 `t14` satisfied `depends_on: [314]` completed via T09 merge `da18e40`)
- `python3 tools/check_architecture.py` → `Loom architecture dependency policy: OK`
- `python3 tools/check_storage_sql_ownership.py` → `storage SQL ownership check passed`
- `git diff --check` → no whitespace errors
- `git diff --stat`/scope review → only the allowed production/test/ledger files plus the explicitly authorized T14-local fixture and its test-only Cargo dependency changed; no `src/lib.rs`/`registry.rs`/`cli.rs`, common harness, other Stage-2 suite, or production runtime/storage edits

Controlled PostgreSQL path: `cv025_to_cv027_postgres_when_available` was run without `LOOM_TEST_POSTGRES_URL`; all three PG cases reported `Skipped` prerequisite, never live `Pass`. T08 marks T14 `PG live = No`, so this is retained as Skipped evidence and is not represented as a live pass.

## Acceptance

- [x] CV-025..CV-027 match the frozen matrix, with causal and bound-World evidence owned by the T14-local fixture.
- [x] Causal child→ancestor visibility is proven by public `direct_causes`/Causes walk; parent-qualified reverse lookup does not discover a child Timeline, and inaccessible sibling reference rejection leaves histories/EventSeq unchanged.
- [x] Catalog authority is proven with exact public capability identity sets for W_a/W_b and a previously bound World returning `Unavailable`/`NotFound` under no active revision without global fallback.
- [x] Production assertions use formal/public surfaces only; runtime/storage traits are confined to controlled T14 fixture setup.
- [x] Dedicated tests + `fmt`/`check`/`clippy` + live InMemory evidence pass; PostgreSQL path remains explicitly Skipped when `LOOM_TEST_POSTGRES_URL` is absent (T08 T14 PG live = No).
- [x] Review pending.

## Stop Conditions

No new production architecture surface required. Public observations use existing `WorldService::create_world_from_template`, `TimelineService::fork`, `ActionService::invoke`, `HistoryService` queries, `CatalogService::catalog`/`catalog_for_world`, and `AdminService::active_runtime_revision`. The T14-local fixture uses runtime/storage only to compose a causal-enabled resolver and retain a valid Binding across a fresh no-active store; it performs no raw table reads and does not modify shared harnesses or implementation semantics.

## Progress Log

- 2026-08-27 — Implemented `apps/loom-validator/src/query_catalog.rs` descriptors `CV-025..027` and `execute_query_catalog` with `cv025`/`cv026`/`cv027` via public surfaces, plus unit tests. Implemented `apps/loom-validator/tests/query_catalog.rs` 7-test suite covering positive InMemory isolation, negative no-active catalog authority, direct formal-surface catalog fallback check, and controlled PostgreSQL prerequisite path. Verified `fmt`/`check`/`clippy`/`test` clean on `InMemory`; `PostgreSQL` prerequisite `Skipped` when not configured (not `Fail`). Created this ledger.
- 2026-08-27 — Reworked the candidate per D-013..D-016: added the T14-local causal fixture and test-only dependencies, corrected CV-026 wording so neutral empty causality is not acceptance evidence, changed no-active validation to a previously bound World, and changed W_a/W_b checks to exact capability identity sets. Re-ran T14 fmt/check/clippy/lib/query_catalog validations; PG remains explicit prerequisite Skipped without `LOOM_TEST_POSTGRES_URL`.
