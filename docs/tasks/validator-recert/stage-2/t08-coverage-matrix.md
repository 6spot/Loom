---
task: VALR-T08
issue: 313
status: in_progress
depends_on: [312]
created_at: 2026-08-26
started_at: 2026-08-27
completed_at:
completion_pr:
merge_sha:
---

# VALR-T08 — Freeze V0 Validator coverage matrix and CV-ID allocation

Contract-only leaf. Freeze the Stage-2 Validator coverage contract before implementation begins. Map current V0 architecture/release-gate capabilities to stable scenario IDs, expected observations, supported evidence classes, prerequisites and owning leaf issues. T10–T18 can be executed independently by lower-capability Executors without choosing semantics themselves.

## Goal

Provide a deterministic, implementable coverage matrix that:

- preserves existing `CV-001..CV-011` stable;
- reserves non-overlapping `CV-012..CV-040` ranges for T10–T18;
- specifies for every planned scenario: stable CV ID, architecture clause, preconditions/fixtures, formal/public Loom surface, expected observable result, supported evidence classes, PostgreSQL live mandatory flag, owning leaf, complementary core/M13 evidence, and explicit unsuitable reason;
- identifies explicit coverage gaps rather than hiding them;
- marks any row requiring a new authority/semantic decision as blocked and escalates.

No scenario behavior, production Validator code, or central registry integration is part of this leaf.

## Scope

Allowed:

- Stage-2 coverage/task documentation and matrix fixtures only;
- reading existing architecture/release records (not rewriting them);
- this ledger record.

Forbidden:

- No production Validator code changes, no `apps/loom-validator/src/` edits, no scenario registry edits;
- No `loom-core` / `loom-runtime` / `loom-storage` / `loom-boundary` / `loom-protocol` / `loom-api` / `loom-client` public API changes;
- No architecture authority invention, no T01–T07 ledger modifications;
- Do not claim capability is validated solely because an internal core test exists;
- Do not merge or close this initiative via self-service; Reviewer acceptance required.

## Existing CV-ID Verification on Current Main `d4437fb`

Base SHA: `d4437fbd332c8e6cac78c3093e0c26f33e8b448b` (origin/main, T07 post-merge audit).

Verification performed on this checkout:

```bash
grep -rn "CV-00" apps/loom-validator/src/ --include="*.rs" | grep -E "const CV_|descriptor\(|ScenarioId::new"
grep -rn "CV-0" docs/tasks/ --include="*.md" | head -n 50
```

Result:

- `CV-001..CV-004` — registered in `apps/loom-validator/src/lifecycle.rs:27-30` via `lifecycle::register` and exercised in `tests/lifecycle.rs`; stable IDs independent of function names; deterministic enumeration sorted by `CV-`.
- `CV-005..CV-009` — registered in `apps/loom-validator/src/scenarios.rs:32-40` via `replay_fork_descriptors` / `register_replay_fork`; exercised in `tests/replay_fork.rs`; gaps documented (`same-Timeline historical materialization not public`, `InMemory durable restart unavailable`).
- `CV-010..CV-011` — registered in `apps/loom-validator/src/runtime_authority.rs:25-26` via `runtime_authority::descriptors`; exercised in `tests/runtime_authority.rs`; negative authority paths.
- `CV-012` appears only in `apps/loom-validator/src/reports.rs` and `apps/loom-validator/tests/authority_gate.rs` as **test fixture IDs** (e.g., `result("CV-012", Pass, ...)`), not as registered production scenarios (`validator_registry` contains exactly `CV-001..CV-011`; `reports.rs` test helper creates transient `ScenarioId` for gate-policy unit tests). No production registry conflict.
- Full sweep for `CV-012..CV-040` in `apps/loom-validator/src/` excluding `#[cfg(test)]` helpers: zero production registrations. `cargo run -q -p loom-validator -- --list` on current main enumerates exactly `CV-001..CV-011` (11 scenarios).

Conclusion: existing stable IDs `CV-001..CV-011` are preserved; new ranges `CV-012..CV-040` are free. No upward move required. Reason recorded: production registry at `d4437fb` contains 11 scenarios, test-only `CV-012`/`CV-013` etc. in report/gate tests are not stable coverage IDs and do not create a conflict.

Allocation decision: keep planned non-overlapping ranges as issued. If a future main introduces a real `CV-012+` before T10 lands, that new range moves upward; existing IDs never renumbered.

## Allocation Table

| Owner Leaf | GitHub | Planned Ledger | CV Range | Count | Status |
| --- | --- | --- | --- | --- | --- |
| T10 World/Binding/Runtime Revision | #315 | `t10-world-revision.md` | `CV-012..CV-014` | 3 | reserved, no conflict |
| T11 Action + durable Ingress | #316 | `t11-action-ingress.md` | `CV-015..CV-017` | 3 | reserved |
| T12 Scheduler + fencing | #317 | `t12-scheduler-fencing.md` | `CV-018..CV-020` | 3 | reserved |
| T13 World Time/Chronology/Reaction | #318 | `t13-world-time.md` | `CV-021..CV-024` | 4 | reserved |
| T14 Query/History/Catalog | #319 | `t14-query-catalog.md` | `CV-025..CV-027` | 3 | reserved |
| T15 Semantic/Blob/Pinned Reads | #320 | `t15-semantic-blob.md` | `CV-028..CV-030` | 3 | reserved |
| T16 Session/Revision/Provenance | #321 | `t16-provenance.md` | `CV-031..CV-033` | 3 | reserved |
| T17 Agency Wake | #322 | `t17-agency.md` | `CV-034..CV-037` | 4 | reserved |
| T18 Change Feed/SSE/formal client | #323 | `t18-change-feed.md` | `CV-038..CV-040` | 3 | reserved |
| (future) T19 central registry | #324 | `t19-registry.md` | — | — | no new CV IDs; integrates `CV-012..040` |
| (future) T20 PostgreSQL live Gate | #325 | `t20-postgres-gate.md` | — | — | no new CV IDs; requires controlled PostgreSQL evidence for certification |

Every new CV ID has exactly one owner leaf (no overlap). `CV-012..CV-040` inclusive = 29 scenarios. Combined Stage-1+Stage-2 stable coverage after this freeze: `CV-001..CV-040` (40 IDs).

## Matrix Overview

The summary table below abbreviates the required matrix columns. The following Detailed Specifications section expands each row to the full 10-field contract so Executors need not choose semantics.

Columns:

1. stable CV ID;
2. capability/architecture clause;
3. preconditions/fixtures;
4. public/formal Loom surface;
5. expected observable result;
6. supported evidence class;
7. PostgreSQL live mandatory for certification;
8. owning leaf;
9. complementary core/M13 evidence (does not replace Validator);
10. explicit unsuitable reason (dash if suitable).

| CV | Capability / Clause | Precondition (short) | Formal Surface (short) | Expected Result (short) | Evidence Classes | PG live? | Owner | Complementary Evidence | Unsuitable Reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CV-012 | World Runtime Binding immutability (`world-runtime.md` §3/§3.4, `m4/t2`) | Template + World birth via composition root with controlled `neutral.counter@^0.1.0` | `WorldService::create_world_from_template`, `TimelineService::inspect_timeline`, `CatalogService::catalog_for_world` | Binding visible via `catalog_for_world` equals birth requirement; second birth with same Template revision yields same semantic requirement set; World shared across Timelines | External, controlled InMemory, controlled PostgreSQL | No | T10 (#315) | `loom-storage` `postgres_lifecycle` binding persistence; `m4/t2` InMemory binding sharing tests | — |
| CV-013 | Compatible active Runtime Revision permits execution (`world-runtime.md` §5, `m4/t4`, `m9/t1`) | Active Runtime Revision compatible with World Binding; composition root provides `loom-neutral` `counter` | `AdminService::active_runtime_revision`, `AdminService::activate_runtime_revision`, `ActionService::invoke` | `Action` `neutral.counter.increment` commits (`ExecutionResult::Committed`) under compatible revision | External, controlled InMemory, controlled PostgreSQL | No | T10 | `loom-storage` `postgres_revision` active/list/activate; `m4/t4` positive lifecycle | — |
| CV-014 | Revision activation does not rewrite World Binding/history (`world-runtime.md` §11, `evolution.md`, `m9/t1`) | World created under R1; list revisions finds compatible R2 | `AdminService::list_runtime_revisions` + `activate_runtime_revision`, `TimelineService::inspect_timeline`, `HistoryService::list_events` | After R2 activation, World Binding unchanged, historical `TimelineVersion` and events still reference R1 provenance; new Timeline fork uses R2 | controlled InMemory, controlled PostgreSQL | Yes (PostgreSQL proves durable history not rewritten) | T10 | `m9/t5` R1/R2 history survives restart; `loom-storage` `postgres_revision` activation neutrality | — |
| CV-015 | Accepted Action → committed Event/Facet (`runtime-contracts.md` §5.4/§6, `core.md` §6) | World/Timeline with `neutral.counter.seed` capability; clean Timeline | `ActionService::invoke`, `QueryService::get_facet`, `HistoryService::list_events` | `seed value=1` commits, `get_facet entity.counter.value == 1`, `list_events` contains committed `EventId` with payload | External, controlled InMemory, controlled PostgreSQL | No | T11 (#316) | `m4/t4` action dispatch; `loom-storage` `postgres_commit` Action commit parity | — |
| CV-016 | Durable Ingress idempotency - duplicate does not create second world mutation (`loom-api` `IngressService`, `m8/t2-t3`) | Valid `IngressEnvelope` (`IngressId`, `IdempotencyKey`, `IngressProvenance`, `IngressTimeMetadata`, `ActionInvocation`) | `IngressService::submit_ingress` / `submit`, `IngressService::ingress_status` / `status`, `HistoryService::list_events` | First `submit` → `Accepted`, second identical `IdempotencyKey` → `Deduplicated` with same `ingress_id`; `list_events` count ==1; `get_facet` value reflects single mutation | controlled InMemory, controlled PostgreSQL (External records but not authority) | Yes (durable dedup must survive restart) | T11 | `m8/t2` ingress persistence idempotency; `loom-storage` ingress tables; http boundary `tests/ingress` | — |
| CV-017 | Ingress operational bookkeeping distinct from World history (`world-runtime.md` §2.5 vs §2.2, `m8/t2`) | Ingress accepted; platform retry/recovery path available via `HttpIngressRecovery` fixture | `IngressService::ingress_status`, `HistoryService::list_events`, `QueryService::get_facet` | Retryable `IngressTechnicalFailure` does not create Event; after recovery via `submit` replay, exactly one committed Event; `IngressStatus` transitions `Accepted/Retryable → Completed(ExecutionResult)` independent of `HistoryService` ordering | controlled InMemory, controlled PostgreSQL | No (but PostgreSQL validates durability of separation) | T11 | `m8/t2` ingress status vs history separation; `m8/t3` processing retry not inventing truth | — |
| CV-018 | Scheduler logical head ordering on one Timeline (`world-runtime.md` §8.3-§8.4, `m5/t4`) | Two Pending Works scheduled in same Timeline at same `WorldInstant` with deterministic `logical_schedule_order` | `TimelineService::inspect_timeline`, `AdminService` logical Work inspection (where public), `ActionService` indirect via Work-bound Action, `HistoryService` for committed order | Only head (`effective_due=T, order=0`) claimable; second work at same `T` remains `Pending` until head completes; history commit order equals logical order regardless of worker arrival race | controlled InMemory, controlled PostgreSQL | Yes (persistence of order must survive restart) | T12 (#317) | `m5/t4` head-aware scheduler claim; `loom-storage` `postgres_work` head ordering | — |
| CV-019 | Stale fencing / ownership cannot commit after authority moved (`world-runtime.md` §8.1, `runtime-contracts.md` §14, `m5/t4`) | Work claimed with lease/fence generation `g`; second worker with stale token | `ActionService` via WorkHandler-equivalent Action, `AdminService::terminalize` (negative), `TimelineService::inspect_timeline` | Stale `complete`/`terminalize` with expired fence returns `Conflict`/`Unavailable`; authoritative history contains only winner's Event; stale worker's second attempt does not create second Event | controlled PostgreSQL (primary), controlled InMemory (logical fence simulation) | Yes | T12 | `loom-storage` `postgres_work_stale_completion` stale fence; `m5/t4` claim fence | — |
| CV-020 | Independent Timelines not globally serialized (`world-runtime.md` §8.4, `m5/t4`) | Two Worlds/Timelines each with Pending Work at same World Time | `TimelineService::fork` (to create sibling), `ActionService::invoke` per Timeline, `HistoryService::list_events` per Timeline | Work on Timeline B commits while Timeline A head remains Pending; no cross-Timeline head barrier | controlled InMemory, controlled PostgreSQL, External | No | T12 | `m5` timeline isolation; `m6/t5` fork ancestry isolation | — |
| CV-021 | Explicit World Time advance via authority path (`world-runtime.md` §6, `m5/t5`) | Timeline quiescent (no semantically due Pending Work); current `WorldInstant` = T10 | `AdminService::advance_world_time` (`AdminAdvanceWorldTimeRequest` with `expected_version`), `TimelineService::inspect_timeline` | `AdvanceWorldTime(T10→T20)` CAS succeeds, `state_revision` increments, `world_time==T20`; replay via `inspect_timeline` at new version shows persisted time | controlled InMemory, controlled PostgreSQL | No | T13 (#318) | `m5/t5` time driver CAS; `loom-storage` timeline logical journal | — |
| CV-022 | Due Work blocks invalid time advancement (`world-runtime.md` §8.5, `m5/t5`) | Timeline has semantically due Pending Work (`effective_due <= world_time`) in backoff | `AdminService::advance_world_time`, `TimelineService::inspect_timeline` | `advance_world_time` returns rejection/Conflict with `due-work quiescence barrier` message; `inspect_timeline.world_time` remains T10; Work not skipped | controlled InMemory, controlled PostgreSQL | Yes (PostgreSQL proves barrier is logical not operational) | T13 | `m5/t5` due-work barrier; `loom-storage` work quiescence | — |
| CV-023 | Chronology reconstruction deterministic from committed history (`world-runtime.md` §9, `m6/t1-t5`) | World with committed Events + logical Time/Work transitions, then restart | `TimelineService::inspect_timeline`, `HistoryService::list_events`, `HistoryService::list_events_page` | After restart, `list_events` order and `EventSeq` equal pre-restart; `world_time` and work order reconstructed from logical journal, not `available_at` or row order | controlled InMemory, controlled PostgreSQL, controlled restart | Yes (restart recovery must be durable) | T13 | `m6/t1-t5` replay determinism; `loom-storage` `postgres_restart_resume` | — |
| CV-024 | Reaction atomicity with triggering commit (`runtime-contracts.md` §5.7, `core.md` §6, `m5/t6`) | Capability reaction registered; committed Event of triggering type | `ActionService::invoke` (trigger), `HistoryService::list_events` + `TimelineService::inspect_timeline` + reaction Work observation via `AdminService` chronological inspection | Triggering Event commit and reaction Immediate Work schedule share same Logical Commit (`TimelineVersion` increments once); no intermediate externally visible half-state (History shows both or neither until Work commits separately per contract) | controlled InMemory, controlled PostgreSQL | No | T13 | `m5/t6` reaction atomic scheduling; `loom-runtime` reaction expansion | — |
| CV-025 | History/trajectory positive isolation - sibling state does not leak (`m6/t5`, `runtime-contracts.md` §9) | World with fork: parent → child A and sibling B; each with branch-local Event | `HistoryService::list_events`, `HistoryService::entity_trajectory`, `TimelineService::inspect_timeline` (`ancestry`) | `list_events(child A)` contains ancestor + A events only, excludes B events and ancestor-future; `entity_trajectory` per Timeline respects same; ordering by `EventSeq` | controlled InMemory, controlled PostgreSQL | No | T14 (#319) | `m6/t5` fork visibility; `loom-storage` `postgres_read` history parity | — |
| CV-026 | Causal/query read branch/world isolation (`m6/t5`, `m7/t1`) | Events with valid causal links (child → ancestor); invalid sibling link attempt | `HistoryService::direct_causes` / `direct_effects` / `causal_walk`, `HistoryService::get_event` | Valid ancestor causal link query succeeds; sibling/unrelated World/ancestor-future causal reference rejected at commit and not returned by `causal_walk`; ordering uses `EventSeq` | controlled InMemory, controlled PostgreSQL | No | T14 | `m6/t5` causality isolation; `m7/t1` history/trajectory reads | — |
| CV-027 | World-scoped Catalog requires Binding + active Revision (`world-runtime.md` §3/§4, `m4/t2`, `m7/t1`) | World with Binding `{counter}` under R-comp; second check with no active revision (test fixture) | `CatalogService::catalog`, `CatalogService::catalog_for_world` | With active compatible revision, `catalog_for_world == {counter}` visible; with no active revision, `catalog_for_world` returns unavailable/empty not fallback to global registry; sibling World with different Binding shows different catalog | controlled InMemory, controlled PostgreSQL | No | T14 | `m4/t2` binding-aware catalog; `m7/t1` binding-aware catalog; `runtime_authority` CV-010/011 negative checks | — |
| CV-028 | Semantic projection rebuildable, not authority (`m7/t2-t3`) | Capability-owned semantic index built from committed Events; then deleted | `CatalogService` discovery, `HistoryService::list_events` (authority), semantic retrieval via controlled host (where public), `QueryService` not used for projection | Delete/rebuild index leaves `list_events`/`get_facet` authority unchanged; similarity query after rebuild returns same source refs (or typed stale) not different history | controlled InMemory, controlled PostgreSQL | No | T15 (#320) | `m7/t2` pgvector projection rebuild; `m7/t3` retrieval not authority | — |
| CV-029 | Blob/reference availability failure does not rewrite history (`m7/t4`) | Facet with Blob reference; BlobStore explicitly missing | `QueryService::get_facet` (Facet contains `BlobReference`), blob read via formal blob API (where public), `HistoryService::list_events` | Blob read returns typed `Unavailable`/`NotFound` with same `FacetSnapshot`; `list_events` history unchanged; replay after blob restore still yields same Event | controlled InMemory, controlled PostgreSQL | No | T15 | `m7/t4` immutable BlobStore; `m7/t4` missing blob not history rewrite | — |
| CV-030 | Pinned/versioned read stable at pinned revision (`m7/t5`, `amendment 0003 §4`) | World at revision `r100`; pinned read handler registered; then new revision `r101` committed | `QueryService::get_facet` via pinned `BaseWorldView` / version-fenced API, `TimelineService::inspect_timeline` (version), `HistoryService::list_events` | Pinned read at `r100` returns value at `r100` even after `r101` exists; not silently following active projection; miss after `r100` pin returns typed `NotFound` | controlled InMemory, controlled PostgreSQL | Yes (pinned consistency must be persistent) | T15 | `m7/t5` scalable pinned reads; amendment 0003 pinned `BaseWorldView` | — |
| CV-031 | Event→Session→Revision provenance retained after revision change (`m9/t2-t3`, `evolution.md`) | Session S1 under R1 commits Event E1 | `HistoryService::list_events` / `get_event`, `AdminService` Session/provenance lookup (`admin::AdminExecutionSession`) | E1's `producing Session` == S1, `S1.runtime_revision == R1` even after R2 activation | controlled InMemory, controlled PostgreSQL, controlled restart | Yes | T16 (#321) | `m9/t2` Session provenance; `m9/t3` Event→Session atomic linkage | — |
| CV-032 | New Session after compatible R2 uses R2 without rewriting history (`m9/t1`, `m9/t5`) | After R2 activation, new Action via new Session S2 | `ActionService::invoke`, `TimelineService::inspect_timeline`, Admin Session inspection | S2's `runtime_revision == R2`; `list_events` for new Event E2 shows S2/R2; reread of E1 still R1 | controlled InMemory, controlled PostgreSQL | Yes | T16 | `m9/t5` R1/R2 session switch; `loom-storage` `postgres_revision` activation | — |
| CV-033 | Implementation/call/entropy provenance tied to committed execution (`m9/t2`) | Session with `ReadSet` / `callGraph` / `entropy sample` | `AdminService` Session evidence fields (`ReadSet` refs, `subresolution call graph`, `entropy`) | Admin-retrieved Session S1 still shows ` capability impl 1.7.3`, `ReadSet` at commit time, not current registry's 1.8.0 | controlled PostgreSQL (durable), controlled InMemory (logical) | No | T16 | `m9/t2` provenance evidence round-trip; `m9/t3` linkage survival after restart | — |
| CV-034 | Agency NoAction completes wake without fabricating Event (`m10/t4`, `amendment 0003 §3.5`) | Scheduled `AgencyWake` with cognition stub returning `Decision::NoAction` | `AdminService::schedule_agency_wake`, Agency wake execution via `TimelineService`/`ActionService` indirect, `HistoryService::list_events` | Wake transitions `Pending→Completed`; `list_events` count unchanged; no new `EventId`; `get_facet` unchanged | controlled InMemory, controlled PostgreSQL | No | T17 (#322) | `m10/t4` NoAction atomic completion; Agency wake commit no-event | — |
| CV-035 | Agency Act enters normal Action authority path (`m10/t4`) | `AgencyWake` with `Decision::Act(neutral.counter.increment)` | `AdminService::schedule_agency_wake`, `ActionService::invoke` authority (via wake), `HistoryService::list_events` + `QueryService::get_facet` | Act commits Event via same resolver/validation/CAS as direct `ActionService::invoke`; facet reflects increment; history contains Event attributable to wake Session | controlled InMemory, controlled PostgreSQL | No | T17 | `m10/t4` Act via normal path; `m10` Agency gate | — |
| CV-036 | Agency semantic rejection produces no false Event (`m10/t4` R-1) | `Act` with invalid payload/authority rejected by Capability | `AdminService::schedule_agency_wake`, `HistoryService::list_events` | Wake completes as determined no-world-change; `ExecutionResult::Rejected`; `list_events` unchanged; later new Wake not blocked by rejected head (R-1) | controlled InMemory, controlled PostgreSQL | No | T17 | `m10/t4` R-1 rejected wake completes; `m10/t5` no stale retry | — |
| CV-037 | Concurrent CAS loser cannot overwrite winner, provenance records path (`m10/t5`) | Two workers claim same wake head with stale/new fence generation | `AdminService::schedule_agency_wake` + concurrent claim via controlled harness, `TimelineService::inspect_timeline`, Admin wake/session provenance | Winner's `TimelineVersion` CAS succeeds, loser's fails with `Conflict`/`ChronologyBudgetExceeded` equivalent; history contains exactly winner's Event; provenance shows `resample` (V0 default) with discard metadata | controlled PostgreSQL (primary), controlled InMemory (logical) | Yes (concurrency + fence must be durable) | T17 | `m10/t5` CAS resample vs reuse; `loom-storage` `postgres_work_stale_completion` | — |
| CV-038 | Committed Event observable via formal change-feed/SSE client (`m8/t4-t6`) | Timeline with committed Event; formal client `SubscriptionRequest::new` | `SubscriptionService::subscribe` / `poll_change_feed`, `HistoryService::list_events` correlation | `ChangeFeedPage`/`SubscriptionResult::Events` contains committed `EventId` with same `EventSeq`/payload as `list_events`; cursor `next_cursor` monotonic | External (real HTTP/SSE), controlled InMemory, controlled PostgreSQL | No | T18 (#323) | `m8/t4` change feed; `m8/t5` HTTP/SSE boundary | — |
| CV-039 | Resume from valid cursor continues at documented boundary (`m8/t4`) | Change feed cursor at `EventSeq=5`; new events `6,7` committed after | `SubscriptionService::subscribe` with `resume_from` cursor, `ChangeFeedCursor::after` | Resume returns `EventSeq 6,7` only, no loss, no duplicate of `5`; `next_cursor` advances correctly | controlled InMemory, controlled PostgreSQL | Yes (cursor durability across restart) | T18 | `m8/t4` resume semantics; `loom-storage` change feed page/cursor | — |
| CV-040 | Disconnect/reconnect recovery preserves history, transport duplicate != world duplicate (`m8/t5-t6`) | Formal client disconnect mid-page; reconnect with same cursor | `SubscriptionService::subscribe` (initial) → disconnect → `subscribe(resume)`, `HistoryService::list_events` | History `list_events` still exactly N authoritative commits; transport retry may deliver page again but `EventId` dedup shows no second commit; `SubscriptionResult` distinguishable `Events` vs `Backpressure`/`Reconnect` | controlled InMemory, controlled PostgreSQL, controlled restart | Yes (reconnect recovery durable) | T18 | `m8/t6` http-client reconnect; `m8/t8` black-box gate | — |

## Detailed Scenario Specifications

Each scenario below expands the 10 required matrix columns so T10–T18 Executors can implement without semantic choice. Any row requiring a new authority decision is marked `blocked` and escalated — none are blocked at freeze; future discovery must mark blocked and stop.

### CV-012 — Immutable World Binding visible through formal reads

- **Stable CV ID:** `CV-012`
- **Capability / Architecture Clause:** `world-runtime.md` §3 (World Runtime Binding), §3.4 v0 immutability, §1 Installed vs Enabled; `m4/t2` Immutable World Runtime Binding; `runtime-contracts.md` §4.4.
- **Preconditions / Fixture Requirements:** Controlled composition root supplies `neutral.counter@^0.1.0` installed. Template `validator.t10.world.binding.v1` revision 1, `WorldInstant(42)` initial time, `requires_capability("neutral.counter","^0.1.0")`. Binding descriptor includes `CapabilityId=neutral.counter`, `versionRequirement=^0.1.0`, `TemplateProvenance`. No prior World with same name.
- **Formal / Public Loom Surface:** `WorldService::create_world_from_template(CreateWorldFromTemplateRequest)` and `TimelineService::inspect_timeline(TimelineTarget)` + `CatalogService::catalog_for_world(WorldId)` via `loom-client::LoomClient`. No `loom-storage`/`loom-runtime` imports in production validator.
- **Expected Observable Result:** `create_world_from_template` returns `TimelineSnapshot { target, version, world_time=42 }`. `catalog_for_world(world_id)` contains `{neutral.counter}` and no extra enabled set. Second independent `create_world_from_template` with same Template revision yields different `WorldId` but identical `CatalogSnapshot` semantic requirement projection. Sibling Timeline fork (`ForkTimelineRequest::new(target)`) shares same `catalog_for_world` result.
- **Supported Evidence Class:** External (`LoomClient` against generic endpoint — reports external evidence), controlled InMemory (`BackendHarness::InMemory` explicit), controlled PostgreSQL (`BackendHarness::PostgreSQL` with valid `LOOM_TEST_POSTGRES_URL` live). Trust via `BackendEvidence` + `BackendHarness::connect`.
- **PostgreSQL Live Mandatory:** No — binding immutability is logical; but PostgreSQL path validates durable persistence across restart (CV-014 covers restart durability; this row demonstrates visible correctness).
- **Owner Leaf:** T10 (#315) — `CV-012..CV-014`
- **Complementary Core / M13 Evidence (does not replace Validator):** `m4/t2` InMemory binding sharing + PostgreSQL lifecycle binding survival; `loom-storage/tests/postgres_lifecycle.rs` `world_runtime_binding_is_persisted_and_immutable` (M13 integrated candidate 19c797d). Internal evidence confirms storage contract; Validator proves public-consumer observation via formal client.
- **Explicit Unsuitable Reason:** — (suitable for public Validator coverage).
- **Fixture Notes for Executor:** Use `apps/loom-validator/tests/common/mod.rs` composition (`Runtime` + `Storage` + `neutral registry` + `loom-boundary::router`) for InMemory/PostgreSQL harnesses. Scope string: `CV-012` fresh per execution.

### CV-013 — Compatible active Runtime Revision permits public Action/read path

- **Stable CV ID:** `CV-013`
- **Capability / Clause:** `world-runtime.md` §5 Execution Session/Assembly, §1.1 Canonical V0 execution path; `runtime-contracts.md` §6.5; `m4/t4` Runtime Revision minimum; `m9/t1` Runtime Revision history.
- **Preconditions:** World from CV-012 birth; Runtime composition confirms active Revision `R_a` with `neutral.counter 1.x` compatible with `^0.1.0` binding via `AdminService::active_runtime_revision`. Policy not switching mid-session.
- **Formal Surface:** `AdminService::active_runtime_revision`, `ActionService::invoke(ActionRequest::for_timeline(world_id, timeline_id, ActionInvocation::new("neutral.counter.seed", ...)))`, `QueryService::get_facet`.
- **Expected Result:** `active_runtime_revision.is_some()` and `revision.capabilities contains neutral.counter@^0.1.0`. `invoke` with valid seed returns `Ok(ExecutionResult::Committed { timeline_version, event_id })` with `event_id` visible via `list_events`. `get_facet(entity, neutral.counter.value)` returns seeded value.
- **Evidence Classes:** External, controlled InMemory, controlled PostgreSQL (trusted only via explicit `BackendEvidence` construction; ambient `LOOM_TEST_POSTGRES_URL` never upgrades External).
- **PostgreSQL Live Mandatory:** No.
- **Owner:** T10
- **Complementary:** `m4/t4` positive lifecycle; `loom-storage/tests/postgres_revision.rs` active/list; internal remainder is storage contract.
- **Unsuitable Reason:** —

### CV-014 — Later compatible revision does not rewrite Binding or historical identity

- **Stable CV ID:** `CV-014`
- **Capability / Clause:** `world-runtime.md` §11.1/§11.2, `evolution.md` Binding requirement vs implementation provenance; `m9/t1`/`m9/t5` revision history surviving restart.
- **Preconditions:** World created under R1 (via CV-012). Fixture publishes compatible R2 (`neutral.counter 1.y` where `^0.1.0` still satisfied) without activating yet. `AdminService::list_runtime_revisions` returns R1,R2.
- **Formal Surface:** `AdminService::activate_runtime_revision(AdminActivateRuntimeRevisionRequest { revision_id: R2.id, expected_generation: Some(gen) })`, `TimelineService::inspect_timeline`, `HistoryService::list_events`, `CatalogService::catalog_for_world`.
- **Expected Result:** Activation succeeds with no World mutation (`HistoryService::list_events` count unchanged immediately after activation). `catalog_for_world` still `{neutral.counter}` (not expanded). New `fork`ed Timeline's first `Action` after activation pins R2 in provenance while reread of pre-activation Event's Session still shows R1 (see provenance leaf for full evidence; this row checks non-rewrite).
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL (External not trusted for durable history check).
- **PostgreSQL Live Mandatory:** Yes — certification requires proof that historical identity survives durable restart/reopen; InMemory positive path suffices for logical non-rewrite, but PostgreSQL proves persistence (controlled PostgreSQL evidence, `BackendEvidence::PostgreSQL` + `controlled-boundary-restart` where applicable).
- **Owner:** T10
- **Complementary:** `m9/t5` R1→R2 historical Sessions keep exact assembly; `loom-storage` `postgres_revision` activation neutrality.
- **Unsuitable Reason:** —

### CV-015 — Accepted Action produces committed Event/Facet/history

- **Stable CV ID:** `CV-015`
- **Clause:** `core.md` §6 No semantic mutation without committed Event; `runtime-contracts.md` §5.4 ActionDefinition/Resolver; `world-runtime.md` §7 Logical Commit.
- **Preconditions:** Clean Timeline with `neutral.counter` enabled; `EntityId` new; `EventId` fresh `Uuid::new_v4()`.
- **Formal Surface:** `ActionService::invoke(ActionRequest { target, invocation: "neutral.counter.seed" payload {event_id, entity_id, value:1}})`, `QueryService::get_facet(FacetQuery::entity)`, `HistoryService::list_events(EventQuery::all(target))`.
- **Expected Result:** `invoke` returns `Committed { timeline_version, state_revision, event_meta }`. `get_facet` returns `Some(FacetSnapshot { value: {"value":1}})`. `list_events`/.`list_events_page` contains `CommittedEvent { id: EventId, type: "neutral.counter.seeded", occurred_at: pinned world_time, payload }` ordered by `EventSeq`.
- **Evidence Classes:** External, controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** No (core semantic path); PostgreSQL validates parity.
- **Owner:** T11 (#316)
- **Complementary:** `m4/t4` Action dispatch; `loom-storage/tests/postgres_commit.rs`; internal validator is storage contract only.
- **Unsuitable Reason:** —

### CV-016 — Durable Ingress idempotency, duplicate does not create second mutation

- **Stable CV ID:** `CV-016`
- **Clause:** `loom-api::IngressService` (`IngressId`, `IdempotencyKey`), `m8/t2` durable Ingress persistence, `m8/t3` normal Session+Action processing; `world-runtime.md` §2.1 vs §2.5 Ingress vs World Truth.
- **Preconditions:** Controlled harness where `IngressService` implemented (PostgreSQL harness with HTTP boundary; InMemory simulation via `IngressEnvelope` typed path). Single World/Timeline target; identical `IdempotencyKey="t11.cv016.key1"` and `IngressId="ingress-cv016-1"`.
- **Formal Surface:** `IngressService::submit_ingress(IngressEnvelope::new(ingress_id, idempotency_key, provenance, authorization, time_metadata, action))` → `IngressAcceptance::{Accepted,Deduplicated}`, `IngressService::ingress_status(IngressId)` → `IngressStatusRecord { status: Completed(Committed)/Retryable }`, `HistoryService::list_events` + `QueryService::get_facet` for authority check.
- **Expected Result:** First `submit` → `Accepted(IngressReceipt { ingress_id, idempotency_key })` and terminal status `Completed(ExecutionResult::Committed)` with one Event. Second `submit` with same `IdempotencyKey` → `Deduplicated(IngressReceipt { existing_ingress_id })` (or `Accepted` deduplicated semantics per `IngressAcceptance` enum) without second `CommittedEvent`. `list_events.len()==1` after both submissions; `get_facet` value equals single seed; no second `EventId`.
- **Evidence Classes:** controlled InMemory (logical dedup), controlled PostgreSQL (durable dedup via `IngressReceipt` persistence). External `LoomClient` submission is visible but `BackendEvidence::External` cannot prove durable idempotency.
- **PostgreSQL Live Mandatory:** Yes — certification requires at least one controlled PostgreSQL evidence where dedup survives process/boundary restart (compose`+`PgStorage`).
- **Owner:** T11
- **Complementary:** `m8/t2` ingress persistence + `ingress` table; `m8/t3` processing; `loom-boundary` HTTP Ingress handler tests.
- **Unsuitable Reason:** —

### CV-017 — Ingress operational bookkeeping distinct from authoritative history

- **Stable CV ID:** `CV-017`
- **Clause:** `world-runtime.md` §2.2 vs §2.5 vs §2.6; `m8/t2` Ingress platform lifecycle; `loom-api::IngressStatus`.
- **Preconditions:** Ingress accepted then `IngressTechnicalFailure` injected via test harness (e.g., `HttpIngressRecovery` fixture forces `Retryable`). History count before recovery recorded.
- **Formal Surface:** `IngressService::ingress_status` polling, `HistoryService::list_events`, `QueryService::get_facet`, second `submit` retry.
- **Expected Result:** After platform `Retryable` failure, `list_events` still count before recovery (0 or prior), `get_facet` unchanged. After retry/success path, `ingress_status` becomes `Completed(ExecutionResult::Committed)` with exactly one new Event; no duplicate factual Events even with transport retry; `IngressStatus::Retryable` never rendered as `Completed(Rejected)`.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** No, but PostgreSQL proves separation survives restart.
- **Owner:** T11
- **Complementary:** `m8/t2` status vs history table separation; `m8/t3` recovery not inventing truth.
- **Unsuitable Reason:** —

### CV-018 — Single-Timeline logical head ordering

- **Stable CV ID:** `CV-018`
- **Clause:** `world-runtime.md` §8.3-§8.4 Deterministic logical Work order, Head-of-line rule; `runtime-contracts.md` §14; `m5/t4` head-aware scheduler claim.
- **Preconditions:** Timeline at `WorldInstant T20`. Two `AdminScheduleAgencyWakeRequest` or equivalent durable Work scheduled via `Action` that creates Immediate Work with same `effective_due_world_time=T20` but distinct `logical_schedule_order` (0,1) via validated `WorkMutation` order. No external wall-clock variance.
- **Formal Surface:** `AdminService::schedule_agency_wake` (where applicable) or `ActionService` that schedules Work via `WorkHandler` return; observation via `TimelineService::inspect_timeline` + logical Work status via `AdminService::AdminTimelineLogicalStatus` (where public) + `HistoryService` commit order. Validator must not query `loom_storage` tables directly in production scenario; InMemory positive proof via `BackendHarness` controlled Work queue visibility is allowed via test harness.
- **Expected Result:** Head `(T20,0)` is only `claimable`; attempt to claim `(T20,1)` before head completion returns `NotFound`/`Unavailable` fence. History commits in order `head→next` regardless of worker lease speed. `EventSeq` order reflects logical order.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL (PostgreSQL proves persistence of order). External generic endpoint not sufficient for ordering proof.
- **PostgreSQL Live Mandatory:** Yes (order must be durable).
- **Owner:** T12 (#317)
- **Complementary:** `m5/t4` claim with `SKIP LOCKED` head-only; `loom-storage/tests/postgres_work.rs` ordering.
- **Unsuitable Reason:** —

### CV-019 — Stale fencing / ownership cannot commit after authority moved

- **Stable CV ID:** `CV-019`
- **Clause:** `world-runtime.md` §8.1 Semantic due vs operational claimability; `runtime-contracts.md` §14 claim/admission; `implementation.md` §13.3 `SKIP LOCKED` scope; `m5/t4`.
- **Preconditions:** Head Work claimed by worker A with fence generation `g1`; lease expired or `AdminService::terminalize` via authorized path moves generation to `g2` held by worker B.
- **Formal Surface:** Dual `BackendContext` or dual harness `InMemoryServer`/`PgServer` claims; observation via `ActionService` indirect Work execution result + `HistoryService` count.
- **Expected Result:** Stale worker A `complete` attempt returns `ApiErrorCode::Conflict` (stale fence) and does not append Event. Winner B's commit appears in `list_events` exactly once. Stale's retry with fresh `inspect_timeline` version requires reschedule not overwrite.
- **Evidence Classes:** controlled PostgreSQL primary (row-level fence), controlled InMemory logical simulation.
- **PostgreSQL Live Mandatory:** Yes.
- **Owner:** T12
- **Complementary:** `loom-storage/tests/postgres_work_stale_completion.rs`; `m5/t4` fence.
- **Unsuitable Reason:** —

### CV-020 — Independent Timelines not globally serialized

- **Stable CV ID:** `CV-020`
- **Clause:** `world-runtime.md` §8.9 Scope, §8.4 head-of-line per Timeline; `m5/t4` timeline isolation.
- **Preconditions:** Two independent Worlds/Timelines `A` and `B` (or fork siblings) each with one due Pending Work.
- **Formal Surface:** `WorldService::create_world_from_template` (two Worlds), `TimelineService::fork` (alternative sibling), `ActionService::invoke` per Timeline, `HistoryService::list_events` per Timeline.
- **Expected Result:** `invoke` on Timeline B commits while Timeline A's head remains Pending; no cross-Timeline `WorldTime advancement forbidden` due to sibling due work; each Timeline's `inspect_timeline` version increments independently.
- **Evidence Classes:** External, controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** No.
- **Owner:** T12
- **Complementary:** `m5` scheduler topology; `m6/t5` fork ancestry isolation.
- **Unsuitable Reason:** —

### CV-021 — Explicit World Time advance via authority path

- **Stable CV ID:** `CV-021`
- **Clause:** `world-runtime.md` §6 World Time is Timeline logical state, §6.3 explicit advancement, §8.7 Time advancement policy; `runtime-contracts.md` §2.2; `m5/t5` time driver.
- **Preconditions:** Timeline quiescent (no Pending Work). `TimelineSnapshot.world_time == T10`. `TimelineVersion { head_event_seq, state_revision }` known.
- **Formal Surface:** `AdminService::advance_world_time(AdminAdvanceWorldTimeRequest { timeline_target, expected_version, next_world_time: T20 })` + `TimelineService::inspect_timeline`.
- **Expected Result:** `advance_world_time` returns `Ok(AdminAdvanceWorldTimeResult { new_version, world_time: T20 })`. `inspect_timeline.version.state_revision` incremented by 1; `world_time==T20`. No fake Event created (`list_events` count unchanged). Replay after restart shows same `world_time`.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** No.
- **Owner:** T13 (#318)
- **Complementary:** `m5/t5` driver CAS; `loom-storage` timeline logical journal.
- **Unsuitable Reason:** —

### CV-022 — Due Work blocks invalid time advancement (quiescence barrier)

- **Stable CV ID:** `CV-022`
- **Clause:** `world-runtime.md` §8.5 Due-work quiescence barrier, §6.3 rule 8, §8.8 auto-advance safety; `m5/t5`.
- **Preconditions:** Timeline at T20 with due Pending Work `W1 (effective_due=T20)` in retry/backoff operationally unclaimable (`available_at > PlatformTime` or missing implementation).
- **Formal Surface:** `AdminService::advance_world_time` attempt `T20→T30`, `TimelineService::inspect_timeline`.
- **Expected Result:** `advance_world_time` returns `Err(ApiError{ code: Conflict/InvalidRequest, message contains "quiescence" or "due Work"})`; `inspect_timeline.world_time` remains T20; `W1` remains `Pending` and remains logical head; `ChronologyBudget` not consumed.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** Yes — must prove barrier is logical (Timeline logical state) not operational (`available_at`/`lease`) and survives restart.
- **Owner:** T13
- **Complementary:** `m5/t5` quiescence barrier; `loom-storage` work barrier.
- **Unsuitable Reason:** —

### CV-023 — Chronology reconstruction deterministic

- **Stable CV ID:** `CV-023`
- **Clause:** `world-runtime.md` §9 Replay and Fork, §9.1 Replay uses two reconstructable histories; `m6/t1-t5` replay; `runtime-contracts.md` §7.
- **Preconditions:** World with Events `E1@T10, E2@T20` + Work order `(T20,0),(T20,1)` + time transitions committed; then simulated restart via `BackendContext::restart` preserving storage.
- **Formal Surface:** `HistoryService::list_events` + `list_events_page(EventQuery::all)` paging, `TimelineService::inspect_timeline` (`ancestry`, `world_time`, `version`), `QueryService::get_facet` for materialized state.
- **Expected Result:** After restart/new `LoomClient`, `list_events` order by `EventSeq` equals pre-restart; `inspect_timeline` `world_time`, `version.state_revision`, and work logical order identical; not derived from `max(event.occurred_at)` or `PostgreSQL natural row order` or `available_at`.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL, controlled restart (`BackendContext::ControlledBoundaryRestart`).
- **PostgreSQL Live Mandatory:** Yes.
- **Owner:** T13
- **Complementary:** `m6/t1-t5` replay; `loom-storage/tests/postgres_restart_resume.rs`.
- **Unsuitable Reason:** —

### CV-024 — Reaction atomicity with triggering commit

- **Stable CV ID:** `CV-024`
- **Clause:** `runtime-contracts.md` §5.7 Reaction Registration, `core.md` §6 Direct Effect vs downstream Reaction, `world-runtime.md` §8.3 last paragraph; `m5/t6` reaction atomic scheduling.
- **Preconditions:** Capability with `Reaction` registered for `EventType "neutral.counter.seeded"` that schedules Immediate Work `reactive-index-work`.
- **Formal Surface:** `ActionService::invoke` (seed), `HistoryService::list_events` + `HistoryService::list_events_page` for atomic observation, `TimelineService::inspect_timeline` for version.
- **Expected Result:** Triggering `Event` commit and reaction Immediate Work schedule share same `Logical Commit` (`TimelineVersion` increments once for the trigger; `list_events` for trigger visible, reaction Work not yet executed but its `Pending` logical state is reconstructable via timeline logical journal; no half-state where Event durable but reaction lost across restart). Second logical commit (Work execution) produces separate Event. Restart between commits preserves both.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** No (atomicity logical; PostgreSQL validates durability).
- **Owner:** T13
- **Complementary:** `m5/t6` reaction atomic scheduling; `loom-runtime` reaction.
- **Unsuitable Reason:** —

### CV-025 — History/trajectory positive isolation - sibling leak excluded

- **Stable CV ID:** `CV-025`
- **Capability / Clause:** `m6/t5` History visibility after fork; `runtime-contracts.md` §9.1; `world-runtime.md` §3.
- **Preconditions:** World fork as in CV-007: parent seeded `value=5`, child fork A incremented to `15`, sibling B untouched. Entity fresh.
- **Formal Surface:** `HistoryService::list_events(EventQuery::all(target))`, `HistoryService::entity_trajectory(EntityTrajectoryQuery::for_timeline(target, entity_id))`, `TimelineService::inspect_timeline` for `ancestry`.
- **Expected Result:** `list_events(child A).len==2` (seed+increment) and `value` via `get_facet==15`; `list_events(sibling B).len==1` and `value==5`; `entity_trajectory(child A)` excludes sibling B events and ancestor-future (if parent later mutated, child history unchanged). Ordering by `EventSeq`.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** No.
- **Owner:** T14 (#319)
- **Complementary:** `m6/t5` child/grandchild visibility; `loom-storage/tests/postgres_read.rs`.
- **Unsuitable Reason:** —

### CV-026 — Causal/query branch/world isolation and ordering

- **Stable CV ID:** `CV-026`
- **Clause:** `m6/t5` Valid causal source; `m7/t1` history/trajectory/causal reads.
- **Preconditions:** Events with causal links: `E2` causal `direct_causes: [E1]` where `E1` is ancestor; also attempt invalid link `E_sibling→E1_sibling`.
- **Formal Surface:** `HistoryService::direct_causes(EventRef)`, `direct_effects`, `causal_walk(CausalQuery)`, `get_event(EventRef)`.
- **Expected Result:** `direct_causes(E2)` returns `[E1]` when `E1` visible via ancestry; `causal_walk` from `E2` traverses only visible ancestry, not sibling. Invalid sibling causality at commit time rejected (second `invoke` with `causal: sibling` returns `Rejected` or `Err`). Ordering uses `EventSeq` not `Uuid`.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** No.
- **Owner:** T14
- **Complementary:** `m6/t5` causality; `loom-storage` causal isolation.
- **Unsuitable Reason:** —

### CV-027 — World-scoped Catalog requires Binding + active Revision

- **Stable CV ID:** `CV-027`
- **Clause:** `world-runtime.md` §3.1 Installed vs Enabled, `m4/t2`, `m7/t1` Binding-aware Catalog, `runtime-contracts.md` §4.4.
- **Preconditions:** Two Worlds: `W_a` binding `{counter}`, `W_b` binding `{counter, observer}`; active Revision R with both capabilities; plus no-active-revision fixture (`RuntimeRevision::none`).
- **Formal Surface:** `CatalogService::catalog()` (global), `CatalogService::catalog_for_world(WorldId)`.
- **Expected Result:** `catalog().capabilities` contains both `counter` and `observer` (installed). `catalog_for_world(W_a)` contains `counter` only; `catalog_for_world(W_b)` contains both. With no active revision, `catalog_for_world` returns unavailable/not-found rather than falling back to `catalog()` content. Validator asserts via formal client, not `loom-registry` table.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** No.
- **Owner:** T14
- **Complementary:** `m4/t2` binding catalog; `runtime_authority` CV-010/011 negative; `m7/t1`.
- **Unsuitable Reason:** —

### CV-028 — Semantic projection rebuildable, not authority

- **Stable CV ID:** `CV-028`
- **Clause:** `m7/t2` semantic indexes + pgvector, `m7/t3` mediator, `implementation.md` placeholder for vector.
- **Preconditions:** Committed Events with `neutral.counter.seed` 3 times; semantic index `semantic_index: neutral.counter.projector@1` built via `Runtime` projection path (Storage `projection_rebuild`).
- **Formal Surface:** Authority: `HistoryService::list_events` + `QueryService::get_facet`; projection: capability-owned semantic retrieval via `FacetSnapshot` host boundary (where public `loom-api` exposes `SemanticIndexDescriptor` via `CatalogService::catalog` and query via `HistoryService` filtered view — actual vector similarity via `loom-storage` projection table not queried directly in production Validator; Validator asserts via rebuild API where present else documents typed unavailable).
- **Expected Result:** Delete projection (`AdminService` projection delete where public) leaves `list_events` count unchanged and `get_facet` value unchanged; rebuild returns same source `EventRef`s and similarity order bounded (not authority). `list_events` after restart still authority.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** No.
- **Owner:** T15 (#320)
- **Complementary:** `m7/t2` pgvector add/rebuild leaves authority unchanged; `m7/t3` read not authority.
- **Unsuitable Reason:** — (projection is rebuildable derived read; not World truth).

### CV-029 — Blob/reference missing does not rewrite history

- **Stable CV ID:** `CV-029`
- **Clause:** `m7/t4` immutable BlobStore; `implementation.md` blob.
- **Preconditions:** Facet `neutral.doc@1` stores `BlobReference` to `BlobStore` (`BlobId`); Blob deleted or never uploaded in test fixture.
- **Formal Surface:** `QueryService::get_facet` returns `FacetSnapshot` with `BlobReference` value even when blob missing; blob read via `loom-api` blob port (where public `BlobService` exists) returns typed `Unavailable`/`NotFound`; `HistoryService::list_events` unchanged.
- **Expected Result:** Blob read failure does not alter `get_facet` authority payload nor `list_events` history; replay after blob re-upload shows same `EventId`/`EventSeq`; failure reported as `ApiErrorCode::Unavailable` not `InvalidRequest` that rewrites Event.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** No.
- **Owner:** T15
- **Complementary:** `m7/t4` blob immutability; `loom-storage` blob tests.
- **Unsuitable Reason:** —

### CV-030 — Pinned/versioned read stable at pinned revision

- **Stable CV ID:** `CV-030`
- **Clause:** `amendment 0003 §4` pinned `BaseWorldView` is consistency contract; `runtime-contracts.md` §6.1-6.2; `m7/t5` scalable pinned reads.
- **Preconditions:** World at `state_revision=100` with value `counter=10`; Service pins `BaseWorldView` at `r100`; then second commit `counter=11` at `r101`.
- **Formal Surface:** `ActionService::invoke` with pinned read handler (Capability-owned semantic read via `ResolutionContext` host) exposed through `QueryService::get_facet` version-fenced query (where public `get_facet_at_version` exists) or indirect via `TimelineSnapshot::version` + `ResolutionContext` read.
- **Expected Result:** Pinned handler reading at `r100` returns `10` even though latest is `11`; fresh `get_facet` without pin returns `11`; `TimelineService::inspect_timeline` at `r100` reconstructs correct value.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** Yes — pinned consistency must be persistent across restart; InMemory positive path suffices logically but certification requires at least one durable evidence.
- **Owner:** T15
- **Complementary:** `m7/t5` pinned reads; amendment 0003 scalable reads.
- **Unsuitable Reason:** —

### CV-031 — Event→Session→Revision provenance retained after revision change

- **Stable CV ID:** `CV-031`
- **Clause:** `m9/t2` Session provenance, `m9/t3` Event↔Session linkage, `evolution.md`.
- **Preconditions:** Session S1 under R1 commits `E1` via `neutral.counter.seed`.
- **Formal Surface:** `ActionService::invoke` (produces S1), `AdminService` provenance query `get_session` / `get_event_session` (where public `AdminService` exposes), fallback via `HistoryService::get_event` + `TimelineSnapshot` provenance field if direct admin not public; validator uses `loom-client` plus `AdminService` via `loom-boundary` admin routes with authorized context.
- **Expected Result:** Before R2 activation, query `EventRef(E1) → Session S1 → Revision R1` succeeds even after `activate_runtime_revision(R2)`. Reread `E1` via `get_event` shows same `session_id`, `revision_id`, `ReadSet` hash.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL, controlled restart.
- **PostgreSQL Live Mandatory:** Yes — provenance must survive durable restart (`PgStorage`).
- **Owner:** T16 (#321)
- **Complementary:** `m9/t3` atomic linkage; `m9/t2` provenance round-trip.
- **Unsuitable Reason:** —

### CV-032 — New Session after compatible R2 uses R2 without rewriting history

- **Stable CV ID:** `CV-032`
- **Clause:** `m9/t1` revision history, `m9/t5` upgrade gate, `world-runtime.md` §11.
- **Preconditions:** After R2 activation compatible with Binding, new Timeline action via Session S2.
- **Formal Surface:** `AdminService::activate_runtime_revision`, `ActionService::invoke` (new), `HistoryService::list_events`, Admin Session inspection.
- **Expected Result:** New Event `E2`'s Session `S2.runtime_revision == R2`; `list_events` for new `EventId` shows `R2`; history reread of `E1` still `R1`. No running Session switches implementation mid-flight.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** Yes (new Session persistence).
- **Owner:** T16
- **Complementary:** `m9/t5` R1→R2 session switch; `loom-storage` `postgres_revision`.
- **Unsuitable Reason:** —

### CV-033 — Implementation/read/call/entropy provenance tied to committed execution

- **Stable CV ID:** `CV-033`
- **Clause:** `m9/t2` ReadSet/call graph/entropy, `runtime-contracts.md` §7.
- **Preconditions:** Session S1 with `ReadSet` containing `entity_facet read` and `entropy sample` and `subresolution call` (counter increment reads dependency). Registry at `counter 1.7.3` during S1; later registry updated to `1.8.0` still compatible.
- **Formal Surface:** `AdminService` Session evidence fields (`ReadSet`, `CallGraph`, `EntropyObservation`) via `AdminExecutionSession`.
- **Expected Result:** After new registry, reread of S1 via Admin shows exact `impl 1.7.3`, `ReadSet` at commit time, not `1.8.0`; call order deterministic; entropy not resampled on replay.
- **Evidence Classes:** controlled PostgreSQL (durable), controlled InMemory (logical).
- **PostgreSQL Live Mandatory:** No, but PostgreSQL required to prove durable provenance storage.
- **Owner:** T16
- **Complementary:** `m9/t2` provenance evidence; `loom-runtime` entropy.
- **Unsuitable Reason:** —

### CV-034 — Agency NoAction completes wake without fabricating Event

- **Stable CV ID:** `CV-034`
- **Clause:** `m10/t4` Atomic Agency Wake Decision/Action commit, NoAction path; `amendment 0003 §3`.
- **Preconditions:** `AgencyWake` scheduled via `AdminService::schedule_agency_wake(AdminScheduleAgencyWakeRequest { agent_id, world_id, timeline_id, due_world_time })` or controlled harness equivalent; cognitive gateway stub returns `Decision::NoAction`.
- **Formal Surface:** `AdminService::schedule_agency_wake`, `HistoryService::list_events` (`list_events.len` before/after), `QueryService::get_facet`, `TimelineService::inspect_timeline` for wake logical completion.
- **Expected Result:** Wake transitions `Pending→Completed` (chronology consumed) with no new `CommittedEvent`; `list_events` count identical before and after; `get_facet` unchanged; second wake can be scheduled at later time.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** No.
- **Owner:** T17 (#322)
- **Complementary:** `m10/t4` NoAction atomic; `loom-agency` contracts.
- **Unsuitable Reason:** —

### CV-035 — Agency Act enters normal Action authority path

- **Stable CV ID:** `CV-035`
- **Clause:** `m10/t4` Act via normal path; `runtime-contracts.md` §8 Agency Decision.
- **Preconditions:** Same wake scheduling but `Decision::Act(ActionInvocation::new("neutral.counter.increment", json!({amount:1})))` with compatible `counter` enabled.
- **Formal Surface:** `AdminService::schedule_agency_wake` + wake execution result via `HistoryService::list_events` correlation and `ActionService` authority shared path.
- **Expected Result:** Wake completion and `Action` commit share atomic `Logical Commit` (single `state_revision` bump per wake). `list_events` gains one `EventId` attributable to wake Session; `get_facet` reflects increment; `catalog_for_world` unchanged.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** No.
- **Owner:** T17
- **Complementary:** `m10/t4` Act via normal path.
- **Unsuitable Reason:** —

### CV-036 — Agency semantic rejection produces no false Event

- **Stable CV ID:** `CV-036`
- **Clause:** `m10/t4` R-1 semantic Rejected MUST complete Wake as determined no-world-change; `runtime-contracts.md` §5.4 Rejected.
- **Preconditions:** Wake `Act` with invalid payload (e.g., `amount: "bad-type"` or missing `entity_id`) that Capability `neutral.counter` rejects.
- **Formal Surface:** `AdminService::schedule_agency_wake`, `HistoryService::list_events`.
- **Expected Result:** Wake completes with `Completed` (not retried forever head-block) and status `Rejected` (distinct from `Retryable` platform failure); `list_events` unchanged; next wake at later time can succeed.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** No.
- **Owner:** T17
- **Complementary:** `m10/t4` R-1; `loom-runtime` rejected path.
- **Unsuitable Reason:** —

### CV-037 — Concurrent/stale CAS loser cannot overwrite winner; provenance records path

- **Stable CV ID:** `CV-037`
- **Clause:** `m10/t5` Agency Wake scheduling CAS policy, resample vs reuse; `world-runtime.md` §8.1; `runtime-contracts.md` §7.3.
- **Preconditions:** Same logical head Wake claimed by two harness workers with stale/new `TimelineVersion`/fence. Controlled concurrency via `PgServer`/`InMemoryServer` dual claims; V0 default policy `resample` unless explicitly `reusable`.
- **Formal Surface:** `AdminService::schedule_agency_wake` concurrent claims, `TimelineService::inspect_timeline` version check, Admin wake/session provenance (`discarded cognition` cost metadata).
- **Expected Result:** Exactly one winner's `Logical Commit` (winner's `state_revision`); loser receives typed `Conflict`/`CAS failure`; history contains winner's Event only once; provenance shows `resample` path and discarded cognition cost without secrets.
- **Evidence Classes:** controlled PostgreSQL primary (fence durability), controlled InMemory logical.
- **PostgreSQL Live Mandatory:** Yes — concurrency and fence must be proven durable.
- **Owner:** T17
- **Complementary:** `m10/t5` stale CAS; `loom-storage/tests/postgres_work_stale_completion.rs`.
- **Unsuitable Reason:** —

### CV-038 — Committed Event observable via formal change-feed/SSE client

- **Stable CV ID:** `CV-038`
- **Clause:** `m8/t4` World Change Feed, `m8/t5` HTTP/SSE boundary, `m8/t6` formal client; `loom-api::SubscriptionService`.
- **Preconditions:** Timeline `T` with `LoomApi` client `LoomClient` over HTTP boundary (`loom-boundary::router`). Committed Event `E_commit` via `ActionService::invoke`.
- **Formal Surface:** `SubscriptionService::subscribe(SubscriptionRequest::new(target, limit=50))` / `poll_change_feed` via `LoomClient`, `HistoryService::list_events` for correlation.
- **Expected Result:** `SubscriptionResult::Events(ChangeFeedPage { events: [E_commit], next_cursor })` where `E_commit.id` equals `list_events` latest `EventId` and `EventSeq` ordering preserved; `next_cursor` monotonic via `ChangeFeedCursor::after(target, EventSeq)`.
- **Evidence Classes:** External (real HTTP/SSE over `LOOM_VALIDATOR_BASE_URL`), controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** No.
- **Owner:** T18 (#323)
- **Complementary:** `m8/t4` feed, `m8/t5` boundary, `m8/t6` client.
- **Unsuitable Reason:** —

### CV-039 — Resume from valid cursor continues at documented boundary without loss/duplicate

- **Stable CV ID:** `CV-039`
- **Clause:** `m8/t4` cursor semantics, `loom-api::ChangeFeedCursor`/`ChangeFeedPage`.
- **Preconditions:** Feed cursor `after(EventSeq=5)` stored; events `6,7` committed after cursor creation.
- **Formal Surface:** `SubscriptionService::subscribe(SubscriptionRequest::resume(target, cursor, limit))` with `cursor=ChangeFeedCursor::after(target, 5)` and `ChangeFeedCursor::from_next_page`.
- **Expected Result:** Resume returns `events: [E6,E7]` only, no `E5`, no gaps; `next_cursor` advances to `7`; second resume from `cursor_after_7` returns empty page with same `next_cursor` (no manufacturing).
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** Yes — cursor durability and resume must survive restart (controlled PostgreSQL evidence).
- **Owner:** T18
- **Complementary:** `m8/t4` cursor; `loom-storage` change feed.
- **Unsuitable Reason:** —

### CV-040 — Disconnect/reconnect recovery preserves history; transport duplicate != world duplicate

- **Stable CV ID:** `CV-040`
- **Clause:** `m8/t5` HTTP/SSE boundary, `m8/t6` client reconnect; `loom-api::SubscriptionReconnect`/`Backpressure`.
- **Preconditions:** Formal SSE/client subscription mid-page; harness forces disconnect (drop `PgServer` boundary task, rebuild on preserved store) or transport-level `Backpressure`.
- **Formal Surface:** `SubscriptionService::subscribe` → disconnect (client sees `SubscriptionResult::Backpressure` or error) → `subscribe(resume_from: Some(cursor))`, `HistoryService::list_events` for authority.
- **Expected Result:** After reconnect, `list_events` still exactly N authoritative commits (no second commit even if transport replays page); change-feed resume from last `next_cursor` returns expected next Events without duplication of already-committed `EventId`s; transport retry distinguishable via `EventId` dedup.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL, controlled restart.
- **PostgreSQL Live Mandatory:** Yes.
- **Owner:** T18
- **Complementary:** `m8/t6` reconnect; `m8/t8` black-box gate.
- **Unsuitable Reason:** —

## Evidence Class Definitions (normative for Stage-2)

- **External** — generic `LoomClient` against `LOOM_VALIDATOR_BASE_URL` without `BackendHarness::connect` controlled construction. `BackendEvidence::External` (`validator:scenario:external`). Never trusted for `required-live` or `controlled restart` gates. May be backed by any implementation; `LOOM_TEST_POSTGRES_URL` never upgrades `External` (VALR-T04).
- **controlled InMemory** — `BackendHarness::connect(BackendKind::InMemory, base_url)` or `BackendContext::for_test_api` with `InMemory` kind + explicit `with_controlled_boundary_restart` where needed. `BackendEvidence::InMemory` trusted for logical correctness but not for durability across real restart (except via `InMemoryServer::restart` harness which preserves store and rebuilds boundary).
- **controlled PostgreSQL** — `BackendHarness::connect(BackendKind::PostgreSQL, base_url)` with valid `LOOM_TEST_POSTGRES_URL` (postgres://) and live endpoint reachable (`catalog()` succeeds). `BackendEvidence::PostgreSQL` trusted. `required-live` policy accepts only this class (`VALR-T06`).
- **controlled restart** — `BackendContext::restart()` path where `RestartCapability::ControlledBoundaryRestart` (VALR-T05). Generic `ReconnectOnly` cannot pass `CV-003/004/014/018/019/022/023/037/039/040` restart-sensitive assertions; must return `Unavailable` with `reconnect-only` evidence.

## PostgreSQL Live Requirement Rationale

Mandatory `Yes` where durability, persistence, or concurrency correctness cannot be observed via `External`/`InMemory` alone:

- `Yes`: CV-014, CV-016, CV-018, CV-019, CV-022, CV-023, CV-030, CV-031, CV-032, CV-037, CV-039, CV-040 (12 rows). Rationale in per-row table.
- `No`: remaining 17 rows validate logical semantics even without live PG; they still exercise PG path when available but remain pass via controlled InMemory.

Certification gate T20 (#325) proves real controlled PostgreSQL live evidence and rejects `skipped`/`unavailable`/fake-PG results (`VALR-T06`).

## Complementary Core / M13 Evidence and Why It Does Not Replace Validator

Validator is public-consumer evidence (`loom-client` / `loom-api` formal surfaces). Internal core/storage tests remain complementary, never sole evidence:

- `m4/t2` binding, `m5/t4` scheduler, `m6/t5` ancestry, `m7` query/semantic/blob/pinned, `m8` Ingress/feed, `m9` provenance, `m10` Agency, plus `loom-storage/tests/postgres_*` persistence contracts.
- M13-T1 closure audit: `loom-validation-candidate` profile passed required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, deny, capacity gates at merge `19c797d`.
- For each CV row, Validator scenario must be implemented on top of existing authority and observed via public API; internal test pass cannot be cited as `Pass` for that CV's public coverage.

## Coverage Gaps Explicitly Recorded (not hidden)

1. **Same-Timeline historical materialization** — `ForkTimelineRequest::at_version` is supported replay; direct same-Timeline historical materialization is not a public operation. Recorded in CV-005 gap and reused for CV-023/025. Validator reports `Unavailable` with `finding:gap:same-timeline-historical-materialization-is-not-a-public-operation` where applicable.
2. **InMemory durable restart** — `CV-009`-class ephemeral InMemory store; controlled PostgreSQL restart is sole durability evidence for `CV-014/023/031/040` etc. InMemory `CV-009` unavailable is expected gap.
3. **Global total ordering of all root inputs** — `world-runtime.md` §8.9: v0 freezes Scheduler-managed Work ordering + World Time barrier, not a global total order over external Action/Ingress/Operator inputs. Validator does not claim such ordering.
4. **Fine-grained ReadSet validation beyond v0 CAS** — `runtime-contracts.md` §7 sequencing is Timeline-wide via `TimelineVersion` CAS in v0; read-set-based concurrency remains deferred (docs/architecture/README.md §4).
5. **Large-World benchmark thresholds** — measured capacity envelope in `docs/capacity-envelope.md`; larger-scale claims marked unproven.
6. **Dynamic per-World Capability hot-plug** — `world-runtime.md` §3.4 v0 immutability; Validator does not cover hot-plug (future architecture review required).
7. **Historical replay checkpoint acceleration** — deferred; `replay` correctness proven via `CV-023` without snapshot optimization.

No new capability scenario invented beyond T10–T18 intents above; any additional need requires Architecture Amendment before coverage claim.

## Stop Conditions / Blocked Rows

- If a required scenario cannot be specified without a new authority/semantic decision, mark that matrix row `blocked` and escalate. Do not invent the missing architecture in T08.
- At freeze, no row is blocked under current `docs/architecture/` + accepted Amendments `0001-0003` authority. The matrix above is implementable via existing `loom-api` surfaces: `WorldService`, `ActionService`, `IngressService`, `TimelineService`, `QueryService`, `HistoryService`, `CatalogService`, `SubscriptionService`, `AdminService`.
- If during T10–T18 implementation a public API cannot observe a required fact without inventing a new authority surface, stop and report coverage gap for architecture review (per each leaf's Stop Conditions).

## Parallel-Safe Implementation Boundary (for T09)

This matrix reserves one disjoint suite module + one test module per owning leaf:

- T10 `world_binding` → `apps/loom-validator/src/world_binding.rs` + `tests/world_binding.rs`
- T11 `action_ingress` → `src/action_ingress.rs` + `tests/action_ingress.rs`
- T12 `scheduler` → `src/scheduler.rs` + `tests/scheduler.rs`
- T13 `world_time` → `src/world_time.rs` + `tests/world_time.rs`
- T14 `query_catalog` → `src/query_catalog.rs` + `tests/query_catalog.rs`
- T15 `semantic_blob` → `src/semantic_blob.rs` + `tests/semantic_blob.rs`
- T16 `provenance` → `src/provenance.rs` + `tests/provenance.rs`
- T17 `agency` → `src/agency.rs` + `tests/agency.rs`
- T18 `change_feed` → `src/change_feed.rs` + `tests/change_feed.rs`

Central registry integration (`T19` #324) alone may edit `apps/loom-validator/src/registry.rs` / `src/lib.rs` `validator_registry` + CLI dispatch. T10–T18 leaf owners must not edit the same registry; use local unit-test registries only. Shared helper contract (e.g., `loom-client` fixture wrapper) is owned by T09 and must be proven common to multiple suites before extraction.

## Verification Evidence

- `python3 tools/validator_ready.py --root docs/tasks/validator-recert/stage-1 --check --format json` → `valid=true`, `violations=[]`, `record_count=7`, `ready=[]`, `blocked=[]` (all VALR-T01..T07 completed).
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert/stage-2 --check --format json` → See Progress Log note on cross-stage dependency: isolated root reports dependency `312` has no task metadata because that Stage-1 record is not under `stage-2`. When checked at `docs/tasks/validator-recert` (both stages) → `valid=true` after this ledger is added with `in_progress`. See command below.
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json` → expected `valid=true`, `violations=[]` (T08 `in_progress` with satisfied dependency `312` completed).
- `python3 tools/check_architecture.py` → `Loom architecture dependency policy: OK`
- `python3 tools/check_storage_sql_ownership.py` → `storage SQL ownership check passed`
- `cargo fmt --all -- --check` → pending CI; local pre-merge candidate must run `cargo fmt --all`, `cargo check`, `cargo clippy`.

## Acceptance

- [x] Every new CV ID has exactly one owner leaf (table above; 29 IDs, disjoint).
- [x] Every planned scenario has expected/public-surface/evidence/prerequisite fields (per-CV specifications).
- [x] Existing CV-001..011 remain stable (verification section).
- [x] Matrix identifies explicit coverage gaps rather than hiding them (Coverage Gaps section, 7 items).
- [ ] Reviewer confirms the matrix is implementable without semantic guesswork (pending independent Reviewer).
- [ ] CI/docs checks complete before marking completed (pending CI).

## Progress Log

- 2026-08-27 — Created `docs/tasks/validator-recert/stage-2/t08-coverage-matrix.md` as contract-only leaf with `status: in_progress`, `depends_on: [312]`, empty `completed_at`/`completion_pr`/`merge_sha`. Froze `CV-012..CV-040` allocation with no conflict (production registry at `d4437fb` contains `CV-001..CV-011`; `CV-012` in `reports.rs` test helpers is not a production registration). Specified per-scenario capability clause, preconditions/fixtures, formal `loom-api` surfaces (`WorldService`/`ActionService`/`IngressService`/`TimelineService`/`QueryService`/`HistoryService`/`CatalogService`/`SubscriptionService`/`AdminService`), expected results, evidence classes, PostgreSQL mandatory flags, owners, complementary core/M13 evidence, and unsuitable reasons. Ensured parallel-safe suite ownership for T09 and escalatable blocked marking. Noted cross-stage `validator_ready` nuance: `--root stage-2` isolated check cannot resolve dependency `312` (lives under `stage-1`); canonical combined `--root docs/tasks/validator-recert` validates correctly. No production code, registry, or T01–T07 files modified.
