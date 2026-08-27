---
task: VALR-T11
issue: 316
status: in_progress
depends_on: [314]
created_at: 2026-08-26
started_at: 2026-08-27
completed_at:
completion_pr:
merge_sha:
---

# VALR-T11 — Validate Action/Event/Facet + durable idempotent Ingress

Owner: T11 (#316) — `CV-015..CV-017`.
Parallel batch: Stage-2 capability batch.
Primary files: `apps/loom-validator/src/action_ingress.rs`, `apps/loom-validator/tests/action_ingress.rs`.
Consumed (read-only): `apps/loom-validator/tests/common/mod.rs` (InMemory/PgServer harnesses).
Forbidden: central registry/dispatch (`src/lib.rs`, `registry.rs`, `scenarios.rs`), other suite/core/runtime/storage/boundary/client APIs.

## Goal

Validate the public Action path and durable idempotent Ingress semantics as observable by an upper-layer Loom consumer through the formal `loom_api`/`loom_client` surface, per `t08-coverage-matrix.md` rows `CV-015..CV-017`.

## Scope

Allowed:

- T11 production module `src/action_ingress.rs` exposing local descriptors/executor for `CV-015..CV-017` via `loom_api` traits and `BackendContext` (no central registration).
- T11 integration tests `tests/action_ingress.rs` using `common::{InMemoryServer, PgServer}` and test-only `loom_runtime`/`loom_storage` dependencies for controlled evidence.
- This ledger `t11-action-ingress.md`.

Forbidden:

- No edit to `src/lib.rs`, `registry.rs`, `scenarios.rs`, CLI/dispatch or central `validator_registry` (T19).
- No scheduler, core, storage, boundary, or client API changes.
- No direct storage table queries from production scenario code; all pass evidence via public `HistoryService::list_events`, `QueryService::get_facet`, `IngressService::submit_ingress`/`ingress_status`.
- No new fault-injection seam or internal-table assertions for `CV-017`.

## Implementation

### Descriptors

`src/action_ingress.rs:59` `descriptors()` returns three `ScenarioDescriptor`:

- `CV-015` — `accepted Action produces committed Event/Facet/history` — `InMemory, PostgreSQL, LoomClient` — `neutral.counter.seed value=1`.
- `CV-016` — `durable Ingress idempotency — duplicate does not create second mutation` — `InMemory, PostgreSQL` — `IngressEnvelope` with `IngressId=ingress-cv016-1`, `IdempotencyKey=t11.cv016.key1`.
- `CV-017` — `Ingress operational bookkeeping distinct from history (blocked)` — `InMemory, PostgreSQL` — always `Unavailable`, no public fault-injection surface.

All use `CAPABILITY_AREA="action-ingress"` and are unregistered until T19.

### CV-015 (AC-01)

`src/action_ingress.rs:282` `cv015()` via `BackendContext::client()` (`WorldService`, `ActionService`, `QueryService`, `HistoryService`):

1. `create_world_from_template(WorldTemplateDescriptor::new("validator.action_ingress.*",1,WorldInstant(42)).requires_capability("neutral.counter","^0.1.0"))`.
2. `invoke(ActionRequest::new(target, ActionInvocation::new("neutral.counter.seed", {"event_id","entity_id","value":1})))` → `ExecutionResult::Committed {event_ids.len==1, event_ids[0]==EventId}`.
3. `get_facet(FacetQuery::new(target, entity, "neutral.counter.value"))` → `Some(FacetSnapshot {value:{"value":1}})`.
4. `list_events(EventQuery::all(target))` → `Vec<CommittedEvent> len 1` with `id==event_id`, `payload.value==1`, ordered by `EventSeq`; also `list_events_page` contains same event and `timeline_version.head_event_seq` advanced.

No `loom-runtime`/`loom-storage` imports in production path.

Evidence in `tests/action_ingress.rs` `cv015_accepted_action_commits_via_in_memory_server`, `cv015_via_loom_client_pumpable_is_committed`, and `cv015_accepted_action_commits_via_pg_with_restart_if_available`; every observation is made through the public `LoomClient` surface.

### CV-016 (AC-02)

`src/action_ingress.rs:415` `cv016()` via `IngressService`:

1. Same fresh World creation.
2. `submit_ingress(IngressEnvelope::new(ingress-cv016-1, t11.cv016.key1, IngressProvenance::new("validator-t11"), target, IngressAuthorizationContext::new({"tenant":"validator-test"}), IngressTimeMetadata::none(), ActionInvocation::new("neutral.counter.seed", {"event_id","entity_id","value":1})))` → first `Accepted(IngressReceipt{ingress_id, idempotency_key})`.
   A first `Deduplicated` receipt is an explicit non-Pass result and cannot be used as this execution's winner.
3. Second identical submit → `Deduplicated(IngressReceipt{ingress_id==first})`.
4. Poll `ingress_status(ingress_id)` up to 40×75ms via public `IngressService` until `Completed(Committed{event_refs.len==1})`; `Failed` is error, `Retryable` is polled, `Accepted/Processing` continue. No `sleep` once, no storage read.
5. `list_events` len 1 with `event_id`, `get_facet` value 1 — exactly one authoritative mutation.
6. If `backend.is_postgres() && can_perform_boundary_restart()`, call `BackendContext::restart()` (real `PgServer` restart via `tests/common/mod.rs`) and re-poll `ingress_status` + `list_events` + `get_facet` via the new `LoomClient` to prove durable dedup survives process/boundary restart. Evidence includes `restart_capability:controlled-boundary-restart`.

`tests/action_ingress.rs:219` `cv016_durable_idempotency_via_loom_client_with_controlled_pump` provides trusted InMemory evidence: `Runtime::process_ingress` is used only as a local controlled worker pump, while acceptance, terminal status, history, facet, and duplicate assertions use the public `LoomClient`/`loom_api` traits. The production-module unit regression `cv016_first_deduplicated_is_an_explicit_non_pass` proves a pre-existing durable record cannot be treated as this execution's winner. `cv016_via_pg_with_restart_if_available` uses the same controlled pump pattern against PostgreSQL and performs a real boundary restart before re-reading status, history, and facet through a new `LoomClient`.

Ingress acceptance is treated as operational bookkeeping only; World truth is `HistoryService` + `FacetSnapshot`.

### CV-017 (AC-03)

`src/action_ingress.rs:802` `cv017()` is `Unavailable` on every backend:

- Frozen matrix marks `Retryable(IngressTechnicalFailure)` as `blocked` — no public API to inject or observe it (`IngressService` only exposes `submit_ingress`/`ingress_status`, no fault-injection).
- Returns `ScenarioOutcome::Unavailable { reason: "Blocked: no public/controlled API..." }` with evidence `validator:gap:CV-017-retry-fault-injection-unavailable`, `restart_capability`, `backend`.
- Never returns `Pass`, never inspects `ingress` table, never adds a new seam or chooses retry semantics.
- `tests/action_ingress.rs` `cv017_blocked_is_unavailable_everywhere` asserts `Unavailable` for `InMemory`, `LoomClient`, and configured `PostgreSQL`; absent PostgreSQL configuration is explicitly recorded as an unavailable prerequisite. Evidence contains `validator:gap:CV-017` and no `storage`/`ingress_table`.

## Race Protocol (enabled for CV-016 only)

- 权威状态: public World/history (`HistoryService::list_events` + `QueryService::get_facet`) after `IngressService` reaches terminal.
- 唯一线性化点: Runtime durable idempotency acceptance keyed by scope + `IdempotencyKey` (`t11.cv016.key1`) + normal Action commit (`neutral.counter.seed`).
- Winner: first `Accepted` for the key; a first `Deduplicated` is an explicit non-Pass result; duplicate: later `Deduplicated` receipt referencing winner's `IngressId`.
- Terminal: `IngressStatus::Completed(Committed{event_refs, timeline_version})` (or explicit `Completed::Rejected` for semantic rejection, not `Retryable`).
- Fence/retry: `CV-017` retry/recovery is `blocked` — no new `R-*` beyond this boundary; any `Retryable`/`Failed`/`Unavailable` is not `Pass`.
- Failure: duplicate must not add second `Event` or facet mutation; history len stays 1 and facet stays `{"value":1}`.

No new coordination state, receipt, fence, or retry logic was added beyond the standard.

## Verification

Required validation (Leader standard `01a03fab-b914-771c-af84-96024113f11d`):

- `cargo fmt --all -- --check`
- `cargo check -p loom-validator --all-targets`
- `cargo clippy -p loom-validator --all-targets -- -D warnings`
- `cargo test -p loom-validator --test action_ingress -- --test-threads=1`
- `cargo test -p loom-validator --all-targets`
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json`
- `python3 tools/check_architecture.py`
- `python3 tools/check_storage_sql_ownership.py`
- `git diff --check`

`action_ingress` tests pass independently; `validator_registry` remains 11. With no explicit PostgreSQL URL, the two PostgreSQL tests record `Skipped` as a non-Pass prerequisite. With `LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_control`, both PostgreSQL scenarios execute live.

## Evidence

- `cargo fmt --all -- --check` — PASS.
- `cargo check -p loom-validator --all-targets` — PASS.
- `cargo clippy -p loom-validator --all-targets -- -D warnings` — PASS with no broad clippy suppression in the T11 test.
- `cargo test -p loom-validator --test action_ingress -- --test-threads=1` — PASS, 9 tests; the no-URL run explicitly records PostgreSQL `Skipped`, and the explicit-URL run executes all PostgreSQL paths.
- `LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_control cargo test -p loom-validator --all-targets` — PASS; 151 unit tests and all integration targets passed, including the first-Deduplicated regression and live CV-015/CV-016 PostgreSQL evidence.
- `python3 tools/check_architecture.py` — PASS.
- `python3 tools/check_storage_sql_ownership.py` — PASS.
- `git diff --check` — PASS.
- PostgreSQL: `PgServer::start()` and the controlled pumpable boundary are exercised; CV-016 performs `controlled-boundary-restart` and re-reads `list_events`/`get_facet`/`ingress_status` via a new `LoomClient`.

## Gaps

- `CV-017` retry/fault-injection remains `blocked` (no public fault-injection seam) — reported as `Unavailable` with reason `no public API to inject or observe Retryable(IngressTechnicalFailure)`. No `Pass` is fabricated, no internal table is read, no seam was added. Requires Architecture Amendment adding a public controlled Ingress failure-injection/observation API before Validator coverage, per `t08-coverage-matrix.md` `CV-017` `Explicit Unsuitable Reason`.
- `CV-016` uses the test-only controlled worker pump because `tests/common/mod.rs` composes the public HTTP boundary without starting the application worker. The pump invokes `Runtime::process_ingress` only; all acceptance, terminal, history, facet, and restart reads are made through `LoomClient`/`loom_api`. This preserves the public consumer contract without adding a second authority or guessing retry semantics.
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json` — PASS (`exit 0`, `valid: true`); the T09 ledger dependency `314` is now eligible on the rebased `origin/main`.

## Non-Goals

- No central registry integration (T19).
- No new `loom_api`/`loom_client` surface or storage semantics.
- No scheduler/time/catalog/provenance/agency/change-feed work.

## Branch

- `agent/executor/200b86f2d7b6` — current candidate, not yet PR/merged.
