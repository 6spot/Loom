---
task: VALR-T10
issue: 315
status: in_progress
depends_on: [314]
created_at: 2026-08-26
started_at: 2026-08-27
completed_at:
completion_pr:
merge_sha:
---

# VALR-T10 — Validate World Binding + positive Runtime Revision lifecycle

Implements the T08 frozen matrix rows `CV-012..CV-014` via the public `loom-api`/`loom-client` surface without reaching into runtime/storage internals. The dedicated suite `src/world_binding.rs` and its integration test `tests/world_binding.rs` are the only production/test files edited; central registry, other Stage-2 suites, and Loom core/storage semantics remain untouched. `CV-014` controlled PostgreSQL evidence and the public-consumer dependency fence are enforced per the matrix; a public API coverage gap would be reported as `needs_decision`.

## Goal

Provide deterministic, public-consumer Validator coverage for:

- **CV-012:** World birth/binding immutability visible through formal reads (`WorldService::create_world_from_template`, `TimelineService::inspect_timeline`, `CatalogService::catalog_for_world`);
- **CV-013:** compatible active Runtime Revision permits the public `Action`/read path (`AdminService::active_runtime_revision` + `ActionService::invoke` + `QueryService::get_facet`/`HistoryService::list_events`);
- **CV-014:** activating/reopening through a later compatible revision does not rewrite the World's immutable binding or historical identity (`AdminService::list_runtime_revisions` + `activate_runtime_revision` + `inspect_timeline`/`list_events`/`catalog_for_world` + fork).

All setup is through controlled test composition; all observation is through the formal/public `LoomApi`/`LoomClient` surface. At least one controlled `InMemory` path is exercised where supported; PostgreSQL is exercised where the matrix marks it required/supported, with `PostgreSQL` live mandatory for `CV-014` certification.

## Scope

Allowed:

- `apps/loom-validator/src/world_binding.rs` — the dedicated World/Binding/Runtime-Revision suite (this leaf's primary production file);
- `apps/loom-validator/tests/world_binding.rs` and its fixture wiring — the dedicated integration-test file (this leaf's primary test file);
- this ledger record `t10-world-revision.md`.

Forbidden (per Leader standard):

- Do not edit the central Validator registry (`src/lib.rs` `validator_registry`, `src/registry.rs`, `src/scenarios.rs`, CLI dispatch); T19 owns registration;
- Do not edit another Stage-2 suite (`src/action_ingress.rs`, `src/scheduler.rs`, etc., or their `tests/*.rs`);
- Do not import `loom-storage`/`sqlx`/`loom-runtime`/`loom-boundary`/`loom-core`/`loom-protocol`/`loom-capability`/`loom-agency`/`loom-neutral` into production suite code; production `src/world_binding.rs` stays on `loom-api`/`loom-client` only (enforced by `tools/check_storage_sql_ownership.py`);
- Do not change Loom core/storage semantics to make the scenario pass;
- Do not invent a new authority surface when the public API cannot observe the required fact — stop and report the coverage gap.

## T08 Contract Mapping

| CV | Capability / Clause | Precondition | Formal Surface | Expected Result | Evidence | PG live? | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CV-012 | World Runtime Binding immutability (`world-runtime.md` §3/§3.4, `m4/t2`) | Template `validator.t10.world.binding.v1` rev 1, `WorldInstant(42)`, `requires_capability("neutral.counter","^0.1.0")` | `WorldService::create_world_from_template`, `TimelineService::inspect_timeline`, `CatalogService::catalog_for_world` via `LoomClient` | `create` returns `TimelineSnapshot { target, version, world_time=42 }`; `catalog_for_world` contains `{neutral.counter}` and no extra; second birth with same revision yields different `WorldId` but identical `CatalogSnapshot`; sibling fork (`ForkTimelineRequest::new`) shares same `catalog_for_world` | External, controlled InMemory, controlled PostgreSQL | No | T10 |
| CV-013 | Compatible active Runtime Revision permits execution (`world-runtime.md` §5, `m4/t4`, `m9/t1`) | Active Runtime Revision compatible with World Binding; composition root provides `loom-neutral` `counter` | `AdminService::active_runtime_revision`, `AdminService::activate_runtime_revision`, `ActionService::invoke` | `active_runtime_revision.is_some()` and caps contain `neutral.counter@^0.1.0`; `invoke` `neutral.counter.seed` commits (`ExecutionResult::Committed`) and is visible via `HistoryService::list_events` + `QueryService::get_facet` | External, controlled InMemory, controlled PostgreSQL | No | T10 |
| CV-014 | Revision activation does not rewrite World Binding/history (`world-runtime.md` §11, `evolution.md`, `m9/t1`) | World created under R1; list revisions finds compatible R2 (`neutral.counter` 1.y where `^0.1.0` still satisfied) | `AdminService::list_runtime_revisions` + `activate_runtime_revision`, `TimelineService::inspect_timeline`, `HistoryService::list_events`, `CatalogService::catalog_for_world` | After R2 activation, World Binding unchanged (`catalog_for_world` still `{neutral.counter}`), historical `TimelineVersion` and events still reference R1 provenance; `list_events` count unchanged immediately after activation; new fork's first `Action` pins R2 while reread of pre-activation Event still shows R1 history | controlled InMemory, controlled PostgreSQL | Yes (PostgreSQL proves durable history not rewritten) | T10 |

Negative/precondition behavior when required revision authority is absent remains distinct from positive lifecycle evidence; the suite does not duplicate or weaken `CV-010`/`CV-011` (runtime_authority negative paths). If the public API cannot observe the required fact without inventing a new authority surface, the scenario reports `Unavailable` with an explicit gap rather than reaching through storage.

## Implementation

### Production suite `apps/loom-validator/src/world_binding.rs`

- Exposes `SUITE = "world_binding"`, `CV_RANGE = "CV-012..CV-014"`, `CAPABILITY_AREA = "world-binding"`, `suite_name()`, `owns_cv()` for disjoint ownership (compatible with T09 scaffold).
- Exposes `descriptors() -> Vec<ScenarioDescriptor>` with the three frozen descriptors; `register_world_binding()` is provided for isolated unit-test registries but is **not** called from `validator_registry()` — global registry stays at 11 until T19.
- Exposes `execute_world_binding(descriptor, ctx) -> ScenarioResult` dispatching to `cv012`/`cv013`/`cv014`. The dispatcher first enforces `supported_backends` (CV-014 does not declare `LoomClient`; external is `Prerequisite`), then PostgreSQL live checks (`LOOM_TEST_POSTGRES_URL` for `CV-014`, live `catalog()` reachability for any PostgreSQL), then the per-CV observation.
- All observation goes through `ctx.client()`/`ctx.api()` (`LoomClient`/`LoomApi`) — `WorldService`, `TimelineService`, `CatalogService`, `AdminService`, `ActionService`, `QueryService`, `HistoryService`. No `loom-storage`/`loom-runtime`/`loom-boundary` import exists in production; `tools/check_storage_sql_ownership.py` passes.
- Helper `world_template_for()` returns the frozen template `validator.t10.world.binding.v1` rev 1 `WorldInstant(42)` `requires_capability("neutral.counter","^0.1.0")`.
- `cv012`: creates World, asserts `world_time==42` via `create` and `inspect_timeline`; fetches `catalog()` + `catalog_for_world` and asserts binding is `{neutral.counter}` (and no `neutral.observer`), world catalog subset of global, second birth with same revision yields different `WorldId` but identical catalog, sibling fork shares same world catalog and ancestry records parent. When global catalog is empty (MockApi), the capability-presence check is vacuous but equality checks still run, keeping the suite green on the mock while still strict on a real service.
- `cv013`: asserts `active_runtime_revision.is_some()` and caps contain `neutral.counter`; creates World, invokes `neutral.counter.seed` value 1, asserts `Committed`, verifies `list_events` contains the event and `get_facet` returns value 1 and version advances. Evidence cites `AdminService::active_runtime_revision`, `ActionService::invoke`, `QueryService::get_facet`, `HistoryService::list_events`.
- `cv014`: requires `ControlledBoundaryRestart` before any restart-sensitive lifecycle operation; `ReconnectOnly` returns `Unavailable` without creating or mutating a World. For a controlled run, it creates a World under R1, seeds value 7 to establish historical identity, captures `list_events` count, `catalog_for_world` ids, `inspect_timeline` version/world_time, and `active_runtime_revision` generation; lists revisions and selects only the suite-owned `validator-t10-r2` whose public `neutral.counter` metadata version satisfies the Binding requirement `^0.1.0`; if that exact compatible publication is absent, returns `Unavailable` without activating a historical revision; activates R2 with `expected_generation`; verifies `list_events` count unchanged and payload unchanged, `catalog_for_world` ids unchanged, `inspect_timeline` version/world_time not rewritten, forks a child and verifies its first `seed` commits under R2 while original history does not leak the fork event, then uses `BackendContext::restart()` to prove durable history/binding survive a real boundary rebuild.

### Integration test `apps/loom-validator/tests/world_binding.rs`

- Retains the scaffold disjointness test (`validator_registry().len()==11`, `CV-012..CV-014` unregistered).
- Adds `world_binding_descriptors_are_three_and_deterministic` (including supported backends per matrix, CV-014 not supporting `LoomClient`).
- `cv012_binding_immutability_passes_on_real_in_memory` / `cv012_binding_immutability_passes_on_live_postgres_when_configured` — real `InMemoryServer` / `PgServer` via `LoomClient` and `BackendContext`; asserts `Pass` and evidence contains `WorldService::create_world_from_template`, `TimelineService::inspect_timeline`, `CatalogService::catalog_for_world` and no `loom_storage`/`loom_runtime`.
- `cv013_compatible_revision_permits_action_passes_on_real_in_memory` / `..._live_postgres_when_configured` — same harnesses; asserts `AdminService::active_runtime_revision` + `ActionService::invoke`.
- `cv014_revision_activation_preserves_binding_on_real_in_memory_with_r2` — custom `InMemoryR2Server` publishes R1, an earlier lexically ordered historical revision with the same capability, and suite-owned `validator-t10-r2`; the controlled context asserts the exact suite-owned R2 is selected, then verifies `Pass` and evidence cites `list_runtime_revisions`/`activate_runtime_revision`/`inspect_timeline`/`list_events`/`catalog_for_world`/`invoke`; verifies no storage import.
- `cv014_revision_activation_preserves_binding_on_live_postgres_with_r2_when_configured` — custom `PgR2Server` applies the same three-publication fixture over `PgStorage` with `migrate`/`health`; with explicit `LOOM_TEST_POSTGRES_URL`, it asserts exact `validator-t10-r2` selection, `Pass`, `backend_evidence:postgresql`, and controlled restart evidence. If the live database is unavailable, it accepts only the validator's correct `Skipped`/`Unavailable`, never a synthetic pass.
- `cv014_reconnect_only_is_unavailable_before_restart_sensitive_lifecycle` — an InMemory context with the default `ReconnectOnly` capability returns `Unavailable` before any World/revision lifecycle operation.
- `cv014_external_backend_is_prerequisite_not_pass` — `BackendContext` with `LoomClient` (External) for `CV-014` correctly yields `Skipped`/`Unavailable`, not `Pass`.
- Revision helpers are defined locally in the test file; `tests/common/mod.rs` is not edited — the historical same-capability publication and suite-owned R2 are isolated to this suite's own fixture wiring, satisfying the "no shared helper unless proven" rule while still providing the matrix-required `list_runtime_revisions` fixture.

## Verification Evidence

- `cargo fmt --all -- --check` → pass (no diff)
- `cargo check -p loom-validator --all-targets` → pass
- `cargo clippy -p loom-validator --all-targets -- -D warnings` → pass
- `LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_control bash tools/test.sh -p loom-validator --test world_binding -- --test-threads=1` → 10 passed (including InMemory/controlled PostgreSQL CV-014 activation, fork and controlled restart, exact suite-owned R2 selection, ReconnectOnly `Unavailable`, external prerequisite, descriptor and scaffold); no ignored
- `cargo test -p loom-validator --all-targets` → suite-local InMemory/Postgres tests pass; global registry still 11 (`cargo run -q -p loom-validator -- --list` enumerates `CV-001..CV-011`)
- `python3 tools/check_architecture.py` → `Loom architecture dependency policy: OK`
- `python3 tools/check_storage_sql_ownership.py` → `storage SQL ownership check passed` (production `src/world_binding.rs` contains no `loom_storage`/`loom_runtime`/`sqlx`/`PgStorage`)
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json` → `valid=true` (when run)
- `git diff --check` → no whitespace errors
- PostgreSQL live evidence for `CV-014` is exercised via `PgR2Server` when `LOOM_TEST_POSTGRES_URL` (or repository default `postgresql://loom:loom@127.0.0.1:15432/loom_control` with `tools/postgres-test.sh` auto-start) is available; controlled `InMemory` evidence is always exercised; `External` is correctly not trusted for `CV-014`.

## Acceptance

- [x] CV-012..CV-014 descriptors, prerequisites, expected/actual evidence match T08 frozen matrix.
- [x] Production suite stays inside public-consumer dependency fence (`loom-api`/`loom-client` only).
- [x] Dedicated tests pass without central-registry edits (`validator_registry().len()==11` unchanged).
- [x] No historical Binding is mutated to satisfy a revision transition (CV-014 asserts `catalog_for_world` and `list_events` unchanged after activation, and fork isolation).
- [x] `fmt`/`check`/`clippy`/`tests` + `check_architecture`/`check_storage_sql_ownership` pass; CI `validator_ready --check` valid.

## Progress Log

- 2026-08-27 — Implemented `src/world_binding.rs` CV-012..CV-014 via public `loom-api`/`loom-client`; added dual-revision controlled harnesses and `tests/world_binding.rs` integration coverage for InMemory and PostgreSQL (including R2 activation and external-backend prerequisite check); verified `validator_registry` remains 11 and dependency fence holds; recorded ledger.
- 2026-08-27 — Rework for Reviewer D-001/D-002: restricted CV-014 to the suite-owned `validator-t10-r2` and public `neutral.counter` version metadata satisfying `^0.1.0`; added an earlier historical same-capability fixture plus exact-selection assertions; made `ReconnectOnly` return `Unavailable` before lifecycle execution; reran the dedicated suite against the explicit controlled PostgreSQL URL with 10/10 passing, including activation/fork/controlled-restart evidence.
