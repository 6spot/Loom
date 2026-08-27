---
task: VALR-T12
issue: 317
status: completed
depends_on: [314]
created_at: 2026-08-26
started_at: 2026-08-27
completed_at: 2026-08-27
completion_pr: 353
merge_sha: 33efd0c865515d6a9437bbc08d0e22648de43373
---

# VALR-T12 — Validate scheduler logical-head admission + stale-work fencing

Executable leaf. Owns `CV-018..CV-020` per frozen `t08-coverage-matrix.md`. Implements
`CV-020` as a deterministic public-surface Timeline independence proof on
controlled `InMemory` and controlled `PostgreSQL`; records `CV-018`/`CV-019`
as blocked gaps without descriptors, registry entries or `Pass` results. No
central registry, `tests/common`, core/runtime/storage/API, or T08 edits are
part of this leaf.

## Goal

Prove from formal Loom surfaces that:
- `CV-018`: work on one Timeline cannot bypass the logical head / required predecessor ordering — **blocked**.
- `CV-019`: stale worker/fence ownership cannot commit authoritative work after authority moved — **blocked**.
- `CV-020`: independent Timelines are not globally serialized by one Timeline's logical-head constraint — **implemented**.

## Scope

Allowed (this leaf only):
- `apps/loom-validator/src/scheduler.rs`
- `apps/loom-validator/tests/scheduler.rs`
- `docs/tasks/validator-recert/stage-2/t12-scheduler-fencing.md` (this ledger)

Forbidden (enforced):
- No central registry edits (`src/registry.rs`, `src/lib.rs` `validator_registry`, CLI) — T19 owns.
- No `tests/common/mod.rs` edits.
- No `loom-core`/`loom-runtime`/`loom-storage`/`loom-boundary`/`loom-api`/`loom-client` public API changes.
- No T08 matrix edits.
- No `Pass` placeholder for blocked rows.

## CV-018 — Single-Timeline logical head ordering (BLOCKED)

- **Status:** `BLOCKED` — no public/controlled `schedule_work`/`claim` surface exists.
- **Frozen T08 reason:** No public `schedule_work` or `claim_work` API; only `AdminService::schedule_agency_wake` (agency wake scheduling) and `AdminService::timeline_logical_status` read exist. `schedule_agency_wake` is agency scheduling only, not generic Work head ordering (`WorkMutation`).
- **Evidence class:** `blocked (no public/controlled schedule/claim surface)`
- **PostgreSQL live mandatory:** No — blocked.
- **Implementation:** No descriptor, no registry entry, no executor, no `Pass`. `scheduler::descriptors()` intentionally excludes `CV-018`; `scheduler::owns_cv("CV-018")==true` only for ownership tracking, not execution.
- **Complementary evidence (does not replace Validator):** `m5/t4` head-aware scheduler claim; `loom-storage/tests/postgres_work.rs` ordering — internal, not public Validator evidence.

## CV-019 — Stale fencing / ownership cannot commit after authority moved (BLOCKED)

- **Status:** `BLOCKED` — no public/controlled fence injection surface.
- **Frozen T08 reason:** No public `claim_work` or fence token injection API; only `AdminService::terminalize_work` (termination) and `AdminService::timeline_logical_status` reads exist. `terminalize_work` is `Pending -> Dead/Cancelled`, not stale `claim`/`complete`.
- **Evidence class:** `blocked (no public/controlled fence surface)`
- **PostgreSQL live mandatory:** No — blocked.
- **Implementation:** No descriptor, no registry entry, no executor, no `Pass`. `scheduler::descriptors()` excludes `CV-019`.
- **Complementary evidence:** `loom-storage/tests/postgres_work_stale_completion.rs`; `m5/t4` fence — internal.

## CV-020 — Independent Timelines not globally serialized (IMPLEMENTED)

- **Architecture clause:** `world-runtime.md` §8.9 Scope, §8.4 head-of-line per Timeline; `m5/t4` timeline isolation.
- **Preconditions (deterministic):** Two independent Worlds at fixed `WorldInstant(100)` via `WorldService::create_world_from_template` with `WorldTemplateDescriptor::new("validator.t12.scheduler.fencing.v1", 1, WorldInstant(100)).requires_capability("neutral.counter","^0.1.0")` plus a public bootstrap `ActionInvocation("neutral.counter.seed")` that creates the Agency Wake agent Entity via the template's `bootstrap_actions` (public `WorldService` setup, no `ActionService` on A). Each Timeline receives one due `Pending` Agency Wake via `AdminService::schedule_agency_wake` with `WorkSchedule::At(WorldInstant(100))` using per-Timeline CAS `expected_version` from creation/status. No wall-clock or platform time is used.
- **Formal surface:**
  - `WorldService::create_world_from_template` (with `bootstrap_actions` for agent setup)
  - `AdminService::schedule_agency_wake(AdminScheduleAgencyWakeRequest { target, expected_version, work_id, agent, cognition, payload, schedule: WorkSchedule::At(100) })`
  - `ActionService::invoke(ActionRequest::new(target_b, ActionInvocation::new("neutral.counter.seed", {"event_id","entity_id","value":1})))` — only on Timeline B post-schedule
  - `AdminService::timeline_logical_status(TimelineTarget)`
  - `TimelineService::inspect_timeline(TimelineTarget)` (`TimelineVersion`, `WorldInstant`)
  - `HistoryService::list_events(EventQuery::all(target))` + `list_events_page`
- **Expected observable result:** `invoke` on Timeline B commits (`ExecutionResult::Committed` with `timeline_version` advancing) while Timeline A's head remains `Pending` at `effective_due=100`. No cross-Timeline head barrier: each Timeline's `inspect_timeline.version` increments independently (`A: version_a0 -> version_a1` via schedule, stable after B commit; `B: version_b0 -> version_b1 -> version_b2` via schedule + commit). A's `timeline_logical_status.version` stays `version_a1` after B commit; `logical_commit_count` for A stable, for B incremented. A's history contains its single bootstrap `Event` (1), B's history contains bootstrap + committed `Event` (2) and `list_events_page` agrees. Ordering by `EventSeq` is preserved. Payload and timeline isolation is strictly per-Timeline.
- **Supported evidence classes:** `controlled InMemory` (trusted), `controlled PostgreSQL` (trusted), `External` (`LoomClient`). InMemory uses `InMemoryServer` (real `Runtime` + `InMemoryStore` over HTTP with preserved store and controlled restart capability); PostgreSQL uses `PgServer` (real `Runtime` + `PgStorage` over HTTP). Both are built via `tests/common/mod.rs` harness; no direct DB/table inspection, no `loom-storage`/`loom-runtime` imports in production code.
- **PostgreSQL live mandatory:** No per T08, but controlled PostgreSQL is implemented and exercised in `tests/scheduler.rs::cv020_independent_timelines_pass_on_live_postgres_service_when_configured` using `PgServer::start()` + `BackendContext` with `BackendKind::PostgreSQL`.
- **Owning leaf:** T12 (#317) — this ledger.
- **Complementary core/M13 evidence:** `m5` scheduler topology; `m6/t5` fork ancestry isolation — internal.
- **Unsuitable reason:** — (suitable).

### CV-020 execution summary

`scheduler::execute_scheduler` dispatches `CV-020` via `cv020()`:

1. Create `A` and `B` Worlds at `WorldInstant 100` (fixed) via `create_world_from_template` with bootstrap seed that creates each Timeline's Agency Wake agent Entity (`neutral.counter.seed` with `bootstrap_event_a/b`). Assert distinct `WorldId`/`TimelineId`, `world_time==100`, and initial history contains the single bootstrap `Event` per Timeline.
2. Schedule one Agency Wake per Timeline at `At(100)` with deterministic `WorkId`/`EntityId`/`cognition` via per-Timeline `expected_version` CAS. Assert `schedule_agency_wake` returns new `version_a1`/`version_b1`.
3. Read `timeline_logical_status` + `inspect_timeline` for both Timelines after schedules: assert `works.len()==1`, `status==Pending`, `effective_due_world_time==100`, `version` matches schedule result, `world_time==100`, histories still `len==1` (bootstrap Event) per Timeline.
4. Invoke `neutral.counter.seed` only on `B` post-schedule (`entity_b`, `event_id_b`, `value=1`) — the sole proving `ActionService::invoke`; `A` receives no `ActionService` invoke. Assert `ExecutionResult::Committed` with `event_ids.len()==1` and `timeline_version==version_b2>version_b1`.
5. Re-read `timeline_logical_status` + `inspect_timeline` + `list_events` + `list_events_page` for both Timelines:
   - `A`: work still `Pending` at `100`, `version==version_a1` unchanged (no global serialization), `logical_commit_count` stable, history `len==1` (bootstrap), `inspect.version==version_a1`.
   - `B`: work still `Pending` at `100`, `version==version_b2`, `logical_commit_count` incremented, `inspect.version==version_b2`, history `len==2` (bootstrap + committed `Event`), `list_events_page` consistent, `A` history does not contain `B`'s committed Event.

All assertions are via formal `loom-api`/`loom-client` surfaces; no `loom-storage` SQL, `available_at`, lease, or `SKIP LOCKED` internals are observed.

## Backend classes

- Controlled `InMemory`: `tests/common::InMemoryServer` (leaked `InMemoryStore` + `Runtime` + `neutral registry` + `loom-boundary::router_with_admin` over `LoomClient`). Evidence `in-memory`, `BackendKind::InMemory`, `restart_capability=controlled-boundary-restart`.
- Controlled `PostgreSQL`: `tests/common::PgServer` (`PgStorage::connect` → `health` → `migrate` → `Runtime` + `PgStorage` + same router/client). Evidence `postgresql`, `BackendKind::PostgreSQL`. Gracefully handles `missing LOOM_TEST_POSTGRES_URL` as `Prerequisite`/`Unavailable`, never as `Pass`.
- Generic `LoomClient` (`External`): supported as execution backend but evidence remains `external` (untrusted).

## Race protocol

Enabled per Leader standard:

- **Authority state:** per-Timeline `AdminTimelineLogicalStatus { works, world_time, version, logical_revision, logical_commit_count }` + `TimelineService::inspect_timeline` (`TimelineVersion`) + `HistoryService::list_events` authoritative `Event` history.
- **Unique linearization points:** each Timeline's Runtime-owned logical commit CAS — `A` schedule commit (`AdminScheduleAgencyWakeRequest` CAS on `expected_version==version_a0`) and `B`'s schedule commit + `B`'s Action commit (`ActionService::invoke` on `TimelineTarget B` CAS). No global commit; `A`'s `Pending` head does not participate in `B`'s commit.
- **Clock boundary:** fixed `WorldInstant(100)` for both Worlds and both `WorkSchedule::At(100)`; no wall/platform time.
- **Winner:** Timeline B's normal Action commit (`ExecutionResult::Committed`, `version_b2>version_b1`).
- **Terminal:** `A` remains `Pending` after `B` commit; `B` Action returns `Committed` and its `TimelineVersion`/`Event` history advances. No Wake execution is performed in this scenario.
- **Fence:** `CV-020` does not claim a fence; `CV-018`/`CV-019` blocked because no public fence/claim authority exists.
- **Failure semantics:** public API/domain failure is scenario failure; infra `Unavailable` can only produce `Unavailable`/`Prerequisite`, never `Pass`; blocked rows remain `BLOCKED` without downgrade to `Pass`.
- **R-*:** `R-T12-01` Timeline-local logical admission, not cross-Timeline serialization; `R-T12-02` blocked claim/fence surface must not be replaced by internal implementation when producing Validator evidence.

## Verification evidence

### Directed validation (this leaf)

- `cargo fmt --all -- --check` — required by canonical procedure.
- `cargo check -p loom-validator --all-targets`
- `cargo clippy -p loom-validator --all-targets -- -D warnings`
- `cargo test -p loom-validator --test scheduler` — exercises:
  - `scheduler_suite_scaffold_is_non_registering_and_disjoint` (suite metadata, registry len==11, `CV-020` absent from central registry, descriptors contains only `CV-020`)
  - `scheduler_cv020_blocked_gaps_have_no_descriptor_or_pass` (asserts `CV-018`/`CV-019` have no descriptor, no Pass, `owns_cv` true)
  - `cv020_independent_timelines_pass_on_real_in_memory_service` — controlled InMemory via `InMemoryServer`, asserts `Pass`, fixed `WorldInstant 100`, independence via public surfaces.
  - `cv020_independent_timelines_pass_on_live_postgres_service_when_configured` — controlled PostgreSQL via `PgServer` when available; otherwise asserts `Unavailable` without synthetic Pass.
- `cargo test -p loom-validator --all-targets` — ensures no cross-suite regression.
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json` (when applicable).
- `git diff --check` — no whitespace errors.

### PostgreSQL live path

Controlled `PgServer::start()` is used as the live path where T08 marks supported. The harness auto-connects to `LOOM_TEST_POSTGRES_URL` or the repository-managed `postgresql://loom:loom@127.0.0.1:15432/loom_control` (via `tools/postgres-test.sh up`), then `health`+`migrate`. Evidence class is `postgresql` with trusted `controlled-boundary-restart`. If the live endpoint is unreachable, the scenario reports `Unavailable`/`Prerequisite`, not `Pass`.

## Acceptance mapping

- **[x] CV-018..CV-020 match T08 exactly:** `CV-020` executable per T08 10-field contract; `CV-018`/`CV-019` strictly blocked per T08 unsuitability reasons, without descriptors or Pass.
- **[x] Stale actor cannot produce an accepted authoritative completion:** `CV-019` blocked gap has no public fence injection surface; `CV-020` does not invent stale claim/complete authority; `terminalize_work` is not used as stale claim/complete.
- **[x] Independent Timelines remain independently progressable:** Proven by `CV-020` — `A` Pending at fixed due does not prevent `B` Committed; per-Timeline CAS, `logical_commit_count`, version, and history isolation observed via public reads.
- **[x] Assertions via formal/public observable state:** All asserts via `WorldService`, `AdminService::schedule_agency_wake`, `AdminService::timeline_logical_status`, `TimelineService::inspect_timeline`, `HistoryService::list_events`/`list_events_page`; no `loom-storage`/`sqlx`/table inspection.
- **[x] Dedicated suite tests, fmt/check/clippy and CI pass; review complete:** See verification evidence above; ledger records true verification commands.

## Blocked-row handling

- `CV-018` and `CV-019` have **no** `ScenarioDescriptor`, no `register_*` call for them, no `Finding` with `Pass`, no central registry (`validator_registry`) entry. `scheduler::owns_cv` retains ownership for ledger/registry disjointness checks only. The absence is asserted in `tests/scheduler.rs`. Future public `schedule_work`/`claim`/`fence` API addition would require an Architecture Amendment before coverage.

## Implementation increment

- `apps/loom-validator/src/scheduler.rs:1-820` — adds `CV_020` descriptor/executor `execute_scheduler`/`cv020` implementing fixed `WorldInstant 100`, per-Timeline `schedule_agency_wake` CAS, `neutral.counter.seed` on `B`, and public-read assertions for independence; keeps `owns_cv`/`SUITE`/`CV_RANGE` scaffold and adds `CV_018`/`CV_019` blocked documentation, `descriptors()`/`register_scheduler()`, `check_postgres_prerequisite`, and `R-T12-01`/`R-T12-02` handling. No core/API/registry edits.
- `apps/loom-validator/tests/scheduler.rs:1-150` — extends scaffold test to assert `CV-018`/`CV-019` blocked and adds controlled `InMemory`/`PostgreSQL` integration tests exercising `scheduler::execute_scheduler(CV-020)` over `InMemoryServer`/`PgServer` with public-surface evidence checks.

## Stop conditions

If deterministic public validation would require introducing a new Scheduler authority or changing fencing semantics, stop and report the architecture gap instead of patching the core from this leaf — satisfied: blocked rows remain blocked, no core patch invented.

## Progress Log

- D-T12-004: completion metadata was recorded before PR acceptance and merge.
- Corrected the lifecycle metadata to remain `in_progress`; `completed_at`, `completion_pr`, and `merge_sha` remain empty until the work is actually accepted and merged.
- Post-merge completion audit: PR #353 was merged as `33efd0c865515d6a9437bbc08d0e22648de43373`; acceptance checklist and completion metadata were finalized on this follow-up audit branch.
