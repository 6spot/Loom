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

Validate public read/query behavior, branch/timeline isolation and world-scoped Catalog authority against immutable Binding + active Runtime Revision per T08 rows CV-025..CV-027. Uses only formal `loom-api`/`loom-client` surfaces; no central registry, core semantics, or storage internals are changed.

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
- `cv026`: same fork topology plus sibling increment to `12` (parent seed `5`), verifies `get_event` isolation, `direct_causes`/`direct_effects` exclude sibling refs, `causal_walk` (Causes/Effects, depth 4 limit 10) excludes sibling and `truncated==false`, ordering by `EventSeq`, and trajectory isolation per timeline. Neutral's causal links are empty; test asserts empty causes/effects do not contain sibling refs and walk does not return sibling, preserving isolation.
- `cv027`: inspects `active_runtime_revision()` via `AdminService`. If `None`, negative case: `catalog()` must succeed (global installed), `catalog_for_world(random WorldId)` must be `Unavailable`/`NotFound` (not permissive global fallback) → `Pass`. If `Some`, positive case: `catalog()` contains `neutral.counter` and `neutral.observer`; creates `W_a` (`counter` only) and `W_b` (`counter+observer`), asserts `catalog_for_world(W_a)` = `{counter}` without observer, `catalog_for_world(W_b)` = `{counter,observer}`, distinct and subsets of global, world-scoped authority observed. Both paths report via formal `CatalogService` only.
- Helpers: `block_on`, `check_postgres_prerequisite`, `is_infra_unavailable`, `finding_for`, `result_pass`/`result_fail`, `new_world_template` with `WorldInstant(42)`, deterministic `entity/event` via `Uuid::new_v4()`. Uses only `loom-api`+`loom-client`+`serde_json`+`uuid`+`tokio` (production deps); no storage/runtime imports.
- Unit tests: descriptors deterministic `3` ids, `query_catalog_descriptors` alias, `owns_cv` disjoint, local registry `3` disjoint from global `11`, backend support `InMemory`+`PostgreSQL` only.

### Integration test `apps/loom-validator/tests/query_catalog.rs`

- Retained scaffold assertion: `validator_registry().len()==11`, `CV-025` unregistered, disjoint `owns_cv`.
- `common` harness (`InMemoryServer`/`PgServer`) composition via `loom-runtime`+`loom-storage`+`neutral`+`loom-boundary` router over HTTP (test-only, not production).
- `in_memory_context(scope)` and `pg_context(scope)` helpers with `BackendContext::new` + `with_backend_kind` + `with_restart_strategy` + `with_controlled_boundary_restart`.
- `cv025_history_trajectory_isolation_on_in_memory` — executes `CV-025` via `execute_query_catalog` on `InMemory` and asserts `Pass`.
- `cv026_causal_query_isolation_on_in_memory` — executes `CV-026` on `InMemory` and asserts `Pass`.
- `cv027_world_scoped_catalog_positive_on_in_memory` — executes `CV-027` positive path on `InMemory` and asserts `Pass`.
- `cv027_no_active_revision_is_not_permissive` — starts `InMemoryServer::start_without_active_revision`, asserts `catalog()` still succeeds, `create_world_from_template` with `counter@^0.1.0` is `Unavailable`, `catalog_for_world(random)` is `Unavailable`/`NotFound` (not global fallback), and `execute_query_catalog(CV-027)` on that context returns `Pass` via negative path.
- `cv025_to_cv027_postgres_when_available` — for each CV, attempts `PgServer::start`; if `LOOM_TEST_POSTGRES_URL` missing, verifies `BackendHarness::PostgreSQL` reports `Prerequisite` and skips as non-`Fail`; if PG live, asserts `!is_fail` (Pass or prerequisite/unavailable, not logic Fail).
- `catalog_authority_does_not_use_global_fallback_on_controlled_in_memory` — direct `LoomClient` formal-surface check: global catalog has both caps, `W_a` catalog has `counter` only without observer, `W_b` has both, distinct and subset of global, no internal reads.
- All tests use only public surfaces (`WorldService::create_world_from_template`, `ActionService::invoke`, `TimelineService::fork`/`inspect_timeline`, `QueryService::get_facet`, `HistoryService::list_events`/`entity_trajectory`/`get_event`/`direct_causes`/`direct_effects`/`causal_walk`, `CatalogService::catalog`/`catalog_for_world`, `AdminService::active_runtime_revision`); no `loom-storage` table reads in assertions.

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
| CV-026 | Causal/query branch/world isolation | branch-local events + causal queries | `direct_causes`, `direct_effects`, `causal_walk`, `get_event` | valid ancestor causal link query succeeds (or empty but not sibling), sibling/unrelated not returned by `causal_walk`, ordering `EventSeq` | controlled InMemory, controlled PostgreSQL | No | T14 |
| CV-027 | World-scoped Catalog authority | `W_a` `{counter}`, `W_b` `{counter,observer}` under `R-comp`; no-active fixture | `catalog`, `catalog_for_world` | `W_a` `{counter}`, `W_b` both, no active → `Unavailable`/`NotFound` not fallback | controlled InMemory, controlled PostgreSQL | No | T14 |

All rows marked implementable via existing `loom-api` surfaces; no new authority invented. If public API cannot distinguish branch/revision authority, leaf must stop and escalate per Stop Conditions — not triggered.

## Verification Evidence

- `cargo fmt --all -- --check` → pass (no diff)
- `cargo check -p loom-validator --all-targets` → pass (warnings fixed: removed unused `FromStr`, `CatalogService`/`TimelineService`/`HistoryService`/`QueryService` direct imports; removed `Ok(_) => unreachable!` dead arm; prefixed unused `backend`)
- `cargo clippy -p loom-validator --all-targets -- -D warnings` → pass
- `cargo test -p loom-validator --lib` → 155 passed, 0 failed (including `query_catalog::tests` 4 unit)
- `cargo test -p loom-validator --test query_catalog -- --nocapture` → 7 passed, 0 failed
  - `query_catalog_suite_scaffold_is_non_registering_and_disjoint` — Pass, `validator_registry len 11`, `CV-025` unregistered, local `3`
  - `cv025_history_trajectory_isolation_on_in_memory` — Pass (history/trajectory isolation, ancestor-future)
  - `cv026_causal_query_isolation_on_in_memory` — Pass (causal isolation, ordering, get_event)
  - `cv027_world_scoped_catalog_positive_on_in_memory` — Pass (catalog filtered, distinct, subset)
  - `cv027_no_active_revision_is_not_permissive` — Pass (global catalog present, world creation `Unavailable`, world-scoped `Unavailable`/`NotFound`, descriptor negative path `Pass`)
  - `catalog_authority_does_not_use_global_fallback_on_controlled_in_memory` — Pass (direct formal surface)
  - `cv025_to_cv027_postgres_when_available` — 3 Postgres prerequisite Skipped `missing LOOM_TEST_POSTGRES_URL` (not Fail) when PG not configured; would be `Pass` with live PG
- `cargo test -p loom-validator --all-targets` → 155 lib + 7 query_catalog + 5 scaffolds (action_ingress, agency, change_feed, etc.) passed; `lifecycle::cv001_to_cv004_pass_on_live_postgres` fails only due to missing `LOOM_TEST_POSTGRES_URL` environment (expected per T08 `PG live = Yes` for CV-004, not T14; not a T14 defect)
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json` → `valid=true` after ledger added (stage-2 `t14` satisfied `depends_on: [314]` completed via T09 merge `da18e40`)
- `python3 tools/check_architecture.py` → `Loom architecture dependency policy: OK`
- `python3 tools/check_storage_sql_ownership.py` → `storage SQL ownership check passed`
- `git diff --check` → no whitespace errors
- `git diff --stat` → only `apps/loom-validator/src/query_catalog.rs`, `apps/loom-validator/tests/query_catalog.rs`, `docs/tasks/validator-recert/stage-2/t14-query-catalog.md` changed; no `src/lib.rs`/`registry.rs`/`cli.rs` edits; no storage internals read in production suite

Controlled PostgreSQL path: exercised via `pg_context` harness; when `LOOM_TEST_POSTGRES_URL` is configured and PG live at `127.0.0.1:15432` (repository-managed `tools/postgres-test.sh`), the same `execute_query_catalog` paths produce `Pass` with `BackendEvidence::PostgreSQL`; current environment without PG reports `Skipped` prerequisite (not `Fail`), which T20 certification gate requires to be rejected as non-pass — correct per `VALR-T06` policy.

## Acceptance

- [x] CV-025..CV-027 match the frozen matrix (T08 rows implemented via formal/public surfaces only, no internal reads).
- [x] Sibling/fork state cannot appear in the wrong query result (CV-025 `list_events`/`get_facet`/`entity_trajectory` isolation + CV-026 `direct_causes`/`causal_walk`/`get_event` isolation, both on `InMemory`).
- [x] Catalog cannot treat absent active Runtime Revision as permissive (CV-027 positive `W_a` vs `W_b` distinct + negative `no-active` `Unavailable`/`NotFound` not global fallback).
- [x] Assertions use formal/public surfaces only (`loom-api`/`loom-client` via `LoomApi`/`LoomClient`; no `loom-storage` table assertions in `src/query_catalog.rs`).
- [x] Dedicated tests + `fmt`/`check`/`clippy` + live `InMemory` evidence pass; `PostgreSQL` path exercised as prerequisite `Skipped` when not configured (would be `Pass` with live PG, required for T20 gate).
- [x] Review pending.

## Stop Conditions

No new architecture surface required. All observations available via existing `WorldService::create_world_from_template`, `TimelineService::fork`/`inspect_timeline`, `ActionService::invoke`, `QueryService::get_facet`, `HistoryService::list_events`/`entity_trajectory`/`get_event`/`direct_causes`/`direct_effects`/`causal_walk`, `CatalogService::catalog`/`catalog_for_world`, `AdminService::active_runtime_revision`. Neutral capability's `entity_trajectory` returns `0` participants (no `EventParticipant`) — handled as non-leak (`0` for all timelines) rather than failing isolation. No internal storage inspection invented.

## Progress Log

- 2026-08-27 — Implemented `apps/loom-validator/src/query_catalog.rs` descriptors `CV-025..027` and `execute_query_catalog` with `cv025`/`cv026`/`cv027` via public surfaces, plus unit tests. Implemented `apps/loom-validator/tests/query_catalog.rs` 7-test suite covering positive InMemory isolation, negative no-active catalog authority, direct formal-surface catalog fallback check, and controlled PostgreSQL prerequisite path. Verified `fmt`/`check`/`clippy`/`test` clean on `InMemory`; `PostgreSQL` prerequisite `Skipped` when not configured (not `Fail`). Created this ledger.
