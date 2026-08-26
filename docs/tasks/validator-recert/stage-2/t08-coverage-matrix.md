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
| CV-016 | Durable Ingress idempotency - duplicate does not create second world mutation (`loom-api` `IngressService`, `m8/t2-t3`) | Valid `IngressEnvelope` (`IngressId`, `IdempotencyKey`, `IngressProvenance`, `target: TimelineTarget`, `authorization`, `time_metadata: IngressTimeMetadata`, `invocation: ActionInvocation`) | `IngressService::submit_ingress(IngressEnvelope::new(ingress_id, idempotency_key, provenance, target, authorization, time_metadata, invocation))` → `IngressAcceptance::{Accepted,Deduplicated(IngressReceipt { ingress_id, idempotency_key })}`, `IngressService::ingress_status(IngressId) -> IngressStatusRecord` + `HistoryService::list_events` | First `submit` → `Accepted(IngressReceipt { ingress_id, idempotency_key })`, second identical `IdempotencyKey` → `Deduplicated(IngressReceipt { ingress_id, idempotency_key })` where `ingress_id` is existing; `list_events` count ==1; `get_facet` value reflects single mutation | controlled InMemory, controlled PostgreSQL (External records but not authority) | Yes (durable dedup must survive restart) | T11 | `m8/t2` ingress persistence idempotency; `loom-storage` ingress tables; http boundary `tests/ingress` | — |
| CV-017 | Ingress operational bookkeeping distinct from World history (`world-runtime.md` §2.5 vs §2.2, `m8/t2`) | No public failure injection — blocked | No public fault-injection surface; only `IngressService::ingress_status` read exists | Blocked: `Retryable(IngressTechnicalFailure)` injection has no public/controlled surface; intent is `Retryable` creates no Event and recovery creates one `EventRef` — gap requires Ingress failure injection API | blocked (no public/controlled fault-injection surface) | No — blocked | T11 | `m8/t2` ingress status vs history separation; `m8/t3` processing retry not inventing truth | No public fault-injection surface — explicit gap, requires Architecture Amendment adding public fault-injection API before Validator coverage |
| CV-018 | Scheduler logical head ordering on one Timeline (`world-runtime.md` §8.3-§8.4, `m5/t4`) | No public Work scheduling/claim — blocked | No public `schedule_work` or `claim` API; only `AdminService::timeline_logical_status` read exists | Blocked: no public/controlled `schedule`/`claim` surface to create and observe head ordering; intent is head-only ordering but current `loom-api` cannot drive two Works via public surface — gap requires scheduler Work API | blocked (no public/controlled schedule/claim surface) | No — blocked | T12 (#317) | `m5/t4` head-aware scheduler claim; `loom-storage` `postgres_work` head ordering | No public `schedule_work`/`claim` API; `schedule_agency_wake` is scheduling only for agency wakes, not generic Work head proof — explicit gap, requires public scheduler Work API before Validator coverage |
| CV-019 | Stale fencing / ownership cannot commit after authority moved (`world-runtime.md` §8.1, `runtime-contracts.md` §14, `m5/t4`) | No public fence injection — blocked | No public `claim`/`complete` or fence token injection API; only `AdminService::terminalize_work` and `AdminService::timeline_logical_status` reads exist | Blocked: no public/controlled `lease`/`fence` injection surface; intent is stale `terminalize_work` returns `Conflict`/`Unavailable` and history contains only winner's Event — gap requires scheduler fence injection API | blocked (no public/controlled fence surface) | No — blocked | T12 | `loom-storage` `postgres_work_stale_completion` stale fence; `m5/t4` claim fence | No public `claim`/`fence` injection API; `terminalize_work` is termination only, not stale claim — explicit gap, requires public fence injection API before Validator coverage |
| CV-020 | Independent Timelines not globally serialized (`world-runtime.md` §8.4, `m5/t4`) | Two Worlds/Timelines each with Pending Work at same World Time | `TimelineService::fork` (to create sibling), `ActionService::invoke` per Timeline, `HistoryService::list_events` per Timeline | Work on Timeline B commits while Timeline A head remains Pending; no cross-Timeline head barrier | controlled InMemory, controlled PostgreSQL, External | No | T12 | `m5` timeline isolation; `m6/t5` fork ancestry isolation | — |
| CV-021 | Explicit World Time advance via authority path (`world-runtime.md` §6, `m5/t5`) | Timeline quiescent (no semantically due Pending Work); current `WorldInstant` = T10 | `AdminService::advance_world_time` (`AdminAdvanceWorldTimeRequest` with `expected_version`), `TimelineService::inspect_timeline` | `AdvanceWorldTime(T10→T20)` CAS succeeds, `state_revision` increments, `world_time==T20`; replay via `inspect_timeline` at new version shows persisted time | controlled InMemory, controlled PostgreSQL | No | T13 (#318) | `m5/t5` time driver CAS; `loom-storage` timeline logical journal | — |
| CV-022 | Due Work blocks invalid time advancement (`world-runtime.md` §8.5, `m5/t5`) | Timeline has semantically due Pending Work (`effective_due <= world_time`) in backoff | `AdminService::advance_world_time`, `TimelineService::inspect_timeline` | `advance_world_time` returns rejection/Conflict with `due-work quiescence barrier` message; `inspect_timeline.world_time` remains T10; Work not skipped | controlled InMemory, controlled PostgreSQL | Yes (PostgreSQL proves barrier is logical not operational) | T13 | `m5/t5` due-work barrier; `loom-storage` work quiescence | — |
| CV-023 | Chronology reconstruction deterministic from committed history (`world-runtime.md` §9, `m6/t1-t5`) | World with committed Events + logical Time/Work transitions, then restart | `TimelineService::inspect_timeline`, `HistoryService::list_events`, `HistoryService::list_events_page` | After restart, `list_events` order and `EventSeq` equal pre-restart; `world_time` and work order reconstructed from logical journal, not `available_at` or row order | controlled InMemory, controlled PostgreSQL, controlled restart | Yes (restart recovery must be durable) | T13 | `m6/t1-t5` replay determinism; `loom-storage` `postgres_restart_resume` | — |
| CV-024 | Reaction atomicity with triggering commit (`runtime-contracts.md` §5.7, `core.md` §6, `m5/t6`) | Capability reaction registered; committed Event of triggering type | `ActionService::invoke` (trigger), `HistoryService::list_events` + `TimelineService::inspect_timeline` + reaction Work observation via `AdminService` chronological inspection | Triggering Event commit and reaction Immediate Work schedule share same Logical Commit (`TimelineVersion` increments once); no intermediate externally visible half-state (History shows both or neither until Work commits separately per contract) | controlled InMemory, controlled PostgreSQL | No | T13 | `m5/t6` reaction atomic scheduling; `loom-runtime` reaction expansion | — |
| CV-025 | History/trajectory positive isolation - sibling state does not leak (`m6/t5`, `runtime-contracts.md` §9) | World with fork: parent → child A and sibling B; each with branch-local Event | `HistoryService::list_events`, `HistoryService::entity_trajectory`, `TimelineService::inspect_timeline` (`ancestry`), `QueryService::get_facet` | `list_events(child A)` contains ancestor + A events only, excludes B events and ancestor-future; `entity_trajectory` per Timeline respects same; `get_facet(child A, entity)` reflects `15` while `get_facet(sibling B)` reflects `5`; ordering by `EventSeq` | controlled InMemory, controlled PostgreSQL | No | T14 (#319) | `m6/t5` fork visibility; `loom-storage` `postgres_read` history parity | — |
| CV-026 | Causal/query read branch/world isolation (`m6/t5`, `m7/t1`) | Events with valid causal links (child → ancestor); invalid sibling link attempt | `HistoryService::direct_causes` / `direct_effects` / `causal_walk`, `HistoryService::get_event` | Valid ancestor causal link query succeeds; sibling/unrelated World/ancestor-future causal reference rejected at commit and not returned by `causal_walk`; ordering uses `EventSeq` | controlled InMemory, controlled PostgreSQL | No | T14 | `m6/t5` causality isolation; `m7/t1` history/trajectory reads | — |
| CV-027 | World-scoped Catalog requires Binding + active Revision (`world-runtime.md` §3/§4, `m4/t2`, `m7/t1`) | World with Binding `{counter}` under R-comp; second check with no active revision (test fixture) | `CatalogService::catalog`, `CatalogService::catalog_for_world` | With active compatible revision, `catalog_for_world == {counter}` visible; with no active revision, `catalog_for_world` returns unavailable/empty does not use global registry; sibling World with different Binding shows different catalog | controlled InMemory, controlled PostgreSQL | No | T14 | `m4/t2` binding-aware catalog; `m7/t1` binding-aware catalog; `runtime_authority` CV-010/011 negative checks | — |
| CV-028 | Semantic projection rebuildable, not authority (`m7/t2-t3`) | Capability-owned semantic index built from committed Events; then deleted | No public SemanticService exists; authority only via `HistoryService::list_events` + `QueryService::get_facet` + `CatalogService::catalog` | Blocked: no public API to create/rebuild/delete/query semantic projection; Validator cannot observe semantic projection via public surface — gap requires new authority | blocked (no public surface) | No | T15 (#320) | `m7/t2` pgvector projection rebuild; `m7/t3` retrieval not authority | No public SemanticService/rebuild API; current `loom-api`/`loom-client` lack semantic projection public surface — explicit gap, requires Architecture Amendment before Validator coverage |
| CV-029 | Blob/reference availability failure does not rewrite history (`m7/t4`) | Facet with Blob reference; BlobStore explicitly missing | No public BlobService exists; authority only via `QueryService::get_facet` (Facet contains `BlobReference` value) + `HistoryService::list_events` | Blocked: no public blob read API; Validator can only observe Facet value via `get_facet`, cannot validate blob fetch failure via public surface — gap requires new authority | blocked (no public surface) | No | T15 | `m7/t4` immutable BlobStore; `m7/t4` missing blob not history rewrite | No public BlobService/blob read API; blob availability cannot be validated via current public `loom-api` — explicit gap, requires Architecture Amendment |
| CV-030 | Pinned/versioned read via fork at version (`m7/t5`, `amendment 0003 §4`) | World at `TimelineVersion { head_event_seq: 10, state_revision: 100 }` value `counter=10`; then second commit `counter=11` at `head_event_seq: 11` | `TimelineService::fork(ForkTimelineRequest::at_version(source, TimelineVersion{10,100}))` then `QueryService::get_facet(FacetQuery::new(fork_target, owner, facet_type))` + `TimelineService::inspect_timeline` | Fork target `get_facet` returns `10` (value at pinned version) even though head `get_facet` returns `11`; fork `inspect_timeline.ancestry` preserves `fork_parent_version` | controlled InMemory, controlled PostgreSQL | Yes (pinned consistency must be persistent) | T15 | `m7/t5` scalable pinned reads via fork-at-version; amendment 0003 | — (implementable via existing `ForkTimelineRequest::at_version` + `get_facet`; no `get_facet_at_version`/`BaseWorldView` invented) |
| CV-031 | Event→Session→Revision provenance retained after revision change (`m9/t2-t3`, `evolution.md`) | Session S1 under R1 commits Event E1 | `HistoryService::list_events`/`get_event` for history, `AdminService::session_for_event(EventRef)` + `AdminService::get_execution_session(AdminExecutionSessionRequest)` for provenance | `AdminService::session_for_event(E1) -> S1` and `get_execution_session(S1).runtime_revision_id == R1` even after R2 activation; `list_events` shows `CommittedEvent` history only | controlled InMemory, controlled PostgreSQL, controlled restart | Yes | T16 (#321) | `m9/t2` Session provenance; `m9/t3` Event→Session atomic linkage | — |
| CV-032 | New Session after compatible R2 uses R2 without rewriting history (`m9/t1`, `m9/t5`) | After R2 activation, new Action via new Session S2 | `ActionService::invoke`, `TimelineService::inspect_timeline`, `AdminService::session_for_event` + `get_execution_session` | `get_execution_session(S2).runtime_revision_id == R2` and `session_for_event(E2) == S2`; `list_events` history reread of E1 still via `get_event` shows `CommittedEvent` unchanged, provenance via `session_for_event(E1) == S1` | controlled InMemory, controlled PostgreSQL | Yes | T16 | `m9/t5` R1/R2 session switch; `loom-storage` `postgres_revision` activation | — |
| CV-033 | Implementation/call/entropy provenance tied to committed execution (`m9/t2`) | Session S1 with `read_set`, `call_provenance`, `entropy_evidence` via `get_execution_session` | `AdminService::get_execution_session(AdminExecutionSessionRequest { session_id }) -> AdminExecutionSession { runtime_revision_id: String, read_set: Vec<AdminReadDependency>, call_provenance: Vec<AdminResolutionCallEdge>, entropy_evidence: AdminEntropyEvidence }` + `AdminService::get_runtime_revision(AdminRuntimeRevisionRequest { revision_id }) -> AdminRuntimeRevision { capabilities: Vec<AdminRuntimeRevisionCapability { implementation_id, version }> }` for version | `get_execution_session(S1).runtime_revision_id == R1` via `get_runtime_revision(R1).capabilities[0].version == "1.7.3"`; `read_set: Vec<AdminReadDependency::Facet { owner, facet_type, schema_revision }>`/`call_provenance`/`entropy_evidence` remain stable | controlled InMemory, controlled PostgreSQL | Yes | T16 | `m9/t2` provenance evidence round-trip; `m9/t3` linkage survival after restart — internal, not public Validator evidence. | `read_set` etc do not carry version; version via `runtime_revision_id` + `get_runtime_revision` |
| CV-034 | Agency NoAction completes wake without fabricating Event (`m10/t4`, `amendment 0003 §3.5`) | No cognitive injection seam — blocked | `cognition: String` is requirement, `AdminService::schedule_agency_wake` only creates `Pending` Work; no controlled `Decision` injection/`execute_work` seam | Blocked: no public/controlled `with_cognitive_executor` + `execute_work` surface; `schedule_agency_wake` only creates `Pending` | blocked (no public/controlled Agency execution surface) | No — blocked | T17 (#322) | `m10/t4` NoAction atomic; `loom-agency` contracts. | `cognition: String` is requirement not `Decision` provider; `schedule_agency_wake` only creates `Pending` Work — explicit gap, requires public Agency execution API before Validator coverage |
| CV-035 | Agency Act enters normal Action authority path (`m10/t4`) | No cognitive injection seam — blocked | No public `Decision` injection; `cognition` String is requirement | Blocked: no public/controlled `with_cognitive_executor` + `execute_work` surface; `schedule_agency_wake` only creates `Pending` | blocked (no public/controlled Agency execution surface) | No — blocked | T17 | `m10/t4` Act via normal path; `m10` Agency gate | No public `Decision` injection — explicit gap, requires public Agency execution API |
| CV-036 | Agency semantic rejection produces no false Event (`m10/t4` R-1) | No cognitive injection seam — blocked | No public `Decision` injection | Blocked: no public/controlled cognitive-injection + `execute_work` surface; `ExecutionResult::Rejected` cannot be observed via `schedule_agency_wake` alone | blocked (no public/controlled Agency execution surface) | No — blocked | T17 | `m10/t4` R-1 rejected wake completes; `m10/t5` no stale retry | No public `Rejected` observation via `schedule_agency_wake` alone — explicit gap, requires public Agency execution API |
| CV-037 | Concurrent CAS loser cannot overwrite winner, provenance records path (`m10/t5`) | No public claim API — blocked | No public claim/execute surface; only `AdminService::schedule_agency_wake` (scheduling) + `AdminService::timeline_logical_status` read exists | Blocked: no public `claim_work` API; intent is winner CAS succeeds (`Conflict` for loser) and `resample` provenance — gap requires scheduler claim API | blocked (no public/controlled claim surface) | No — blocked | T17 | `m10/t5` CAS resample vs reuse; `loom-storage` `postgres_work_stale_completion` | No public concurrent claim/execute API; `schedule_agency_wake` is scheduling only — explicit gap, requires public scheduler claim API before Validator coverage |
| CV-038 | Committed Event observable via formal change-feed/SSE client (`m8/t4-t6`) | Timeline with committed Event; formal client `SubscriptionRequest::new` | `SubscriptionService::subscribe` / `poll_change_feed`, `HistoryService::list_events` correlation | `ChangeFeedPage`/`SubscriptionResult::Events` contains committed `EventId` with same `EventSeq`/payload as `list_events`; cursor `next_cursor` monotonic | External (real HTTP/SSE), controlled InMemory, controlled PostgreSQL | No | T18 (#323) | `m8/t4` change feed; `m8/t5` HTTP/SSE boundary | — |
| CV-039 | Resume from valid cursor continues at documented boundary (`m8/t4`) | Change feed cursor at `EventSeq=5`; new events `6,7` committed after | `SubscriptionService::subscribe(SubscriptionRequest::resume(target, cursor, limit))` with `ChangeFeedCursor::after(target, 5)` and `ChangeFeedPage.next_cursor: Option<ChangeFeedCursor>` | Resume returns `EventSeq 6,7` only, no loss, no duplicate of `5`; `next_cursor` (`Option<ChangeFeedCursor>`) advances correctly | controlled InMemory, controlled PostgreSQL | Yes (cursor durability across restart) | T18 | `m8/t4` resume semantics; `loom-storage` change feed page/cursor | — |
| CV-040 | Disconnect/reconnect recovery preserves history, transport duplicate != world duplicate (`m8/t5-t6`) | Formal client disconnect mid-page; reconnect with same cursor | `SubscriptionService::subscribe(SubscriptionRequest::new(target, limit))` → disconnect → `SubscriptionService::subscribe(SubscriptionRequest::resume(target, cursor, limit))`, `HistoryService::list_events` + `ChangeFeedPage.next_cursor: Option<ChangeFeedCursor>` | History `list_events` still exactly N authoritative commits; transport retry may deliver page again but `EventId` dedup shows no second commit; `SubscriptionResult::Events(ChangeFeedPage)` vs `Backpressure`/`Reconnect` distinguishable | controlled InMemory, controlled PostgreSQL, controlled restart | Yes (reconnect recovery durable) | T18 | `m8/t6` http-client reconnect; `m8/t8` black-box gate | — |

## Detailed Scenario Specifications

Each scenario below expands the 10 required matrix columns so T10–T18 Executors can implement without semantic choice. Any row requiring a new authority decision is marked `blocked` and escalated — at freeze 9 rows are blocked (`CV-017`, `CV-018`, `CV-019`, `CV-028`, `CV-029`, `CV-034`, `CV-035`, `CV-036`, `CV-037`) for missing public/controlled Agency/scheduler/fault-injection API (see Coverage Gaps 8/9/11/12/13/14/15/16/17); all others implementable via existing `loom-api`/`loom-client`; future discovery of additional missing authority must also mark blocked and stop.

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
- **Expected Result:** `active_runtime_revision.is_some()` and `revision.capabilities contains neutral.counter@^0.1.0`. `invoke` with valid seed returns `Ok(ExecutionResult::Committed { event_ids: Vec<EventId>, timeline_version: TimelineVersion })` with `event_ids[0]` visible via `HistoryService::list_events`/`get_event`; `QueryService::get_facet(FacetQuery::new(target, FacetOwner::entity(entity_id), FacetTypeId::from("neutral.counter.value")))` returns seeded value.
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
- **PostgreSQL Live Mandatory:** Yes — certification requires proof that historical identity survives durable restart/reopen; InMemory positive path suffices for logical non-rewrite, but PostgreSQL proves persistence (controlled PostgreSQL evidence, `BackendEvidence::PostgreSQL` + `controlled-boundary-restart` controlled harness via `BackendContext::restart()` + `RestartCapability::ControlledBoundaryRestart`).
- **Owner:** T10
- **Complementary:** `m9/t5` R1→R2 historical Sessions keep exact assembly; `loom-storage` `postgres_revision` activation neutrality.
- **Unsuitable Reason:** —

### CV-015 — Accepted Action produces committed Event/Facet/history

- **Stable CV ID:** `CV-015`
- **Clause:** `core.md` §6 No semantic mutation without committed Event; `runtime-contracts.md` §5.4 ActionDefinition/Resolver; `world-runtime.md` §7 Logical Commit.
- **Preconditions:** Clean Timeline with `neutral.counter` enabled; `EntityId` new; `EventId` fresh `Uuid::new_v4()`.
- **Formal Surface:** `ActionService::invoke(ActionRequest { target, invocation: "neutral.counter.seed" payload {event_id, entity_id, value:1}})`, `QueryService::get_facet(FacetQuery::new(target, FacetOwner::entity(entity_id), FacetTypeId::from("neutral.counter.value")))`, `HistoryService::list_events(EventQuery::all(target))`.
- **Expected Result:** `invoke` returns `Ok(ExecutionResult::Committed { event_ids: Vec<EventId>, timeline_version: TimelineVersion })` where `event_ids.len()==1` (`event_ids[0]` is `CommittedEvent.id`). `get_facet` returns `Some(FacetSnapshot { value: {"value":1}, schema_revision })`. `HistoryService::list_events(EventQuery::all(target)) -> Vec<CommittedEvent>` with `CommittedEvent { id, timeline_id, sequence: EventSeq, event_type: EventTypeId, schema_revision, occurred_at: WorldInstant, payload: Value, effects: Vec<WorldEffect> }` ordered by `sequence` (`EventSeq`), and `HistoryService::list_events_page(EventQuery::all(target)) -> EventPage { events: Vec<CommittedEvent>, next_after: Option<EventSeq> }` where `events[0].id == event_ids[0]`; `timeline_version.head_event_seq` advances by 1.
- **Evidence Classes:** External, controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** No (core semantic path); PostgreSQL validates parity.
- **Owner:** T11 (#316)
- **Complementary:** `m4/t4` Action dispatch; `loom-storage/tests/postgres_commit.rs`; internal validator is storage contract only.
- **Unsuitable Reason:** —

### CV-016 — Durable Ingress idempotency, duplicate does not create second mutation

- **Stable CV ID:** `CV-016`
- **Clause:** `loom-api::IngressService` (`IngressId`, `IdempotencyKey`), `m8/t2` durable Ingress persistence, `m8/t3` normal Session+Action processing; `world-runtime.md` §2.1 vs §2.5 Ingress vs World Truth.
- **Preconditions:** Controlled harness where `IngressService` implemented (PostgreSQL harness with HTTP boundary; InMemory simulation via `IngressEnvelope` typed path). Single World/Timeline target; identical `IdempotencyKey="t11.cv016.key1"` and `IngressId="ingress-cv016-1"`.
- **Formal Surface:** `IngressService::submit_ingress(IngressEnvelope::new(ingress_id: IngressId, idempotency_key: IdempotencyKey, provenance: IngressProvenance, target: TimelineTarget, authorization: IngressAuthorizationContext, time_metadata: IngressTimeMetadata, invocation: ActionInvocation))` → `IngressAcceptance::{Accepted,Deduplicated}` (`IngressReceipt { ingress_id, idempotency_key }` + `IdempotencyConflict` on conflict), `IngressService::ingress_status(IngressId) -> IngressStatusRecord { ingress_id, idempotency_key, status: IngressStatus }`, `HistoryService::list_events` + `QueryService::get_facet` for authority check.
- **Expected Result:** First `submit` → `Accepted(IngressReceipt { ingress_id, idempotency_key })` and terminal `IngressStatusRecord { status: IngressStatus::Completed(IngressCompletion::Committed { event_refs: Vec<EventRef>, timeline_version: TimelineVersion }) }` with `event_refs.len()==1` (one `EventRef`). Second `submit` with same `IdempotencyKey` → `Deduplicated(IngressReceipt { ingress_id, idempotency_key })` where `ingress_id` equals first `ingress_id`; no second committed `EventRef` (conflict would be `IdempotencyConflict { idempotency_key, existing_ingress_id, existing_request_fingerprint, submitted_request_fingerprint }` only on differing payload). `list_events.len()==1` after both submissions; `get_facet` value equals single seed; no second `EventId`.
- **Evidence Classes:** controlled InMemory (logical dedup), controlled PostgreSQL (durable dedup via `IngressReceipt` persistence). External `LoomClient` submission is visible but `BackendEvidence::External` cannot prove durable idempotency.
- **PostgreSQL Live Mandatory:** Yes — certification requires at least one controlled PostgreSQL evidence where dedup survives process/boundary restart (compose`+`PgStorage`).
- **Owner:** T11
- **Complementary:** `m8/t2` ingress persistence + `ingress` table; `m8/t3` processing; `loom-boundary` HTTP Ingress handler tests.
- **Unsuitable Reason:** —

### CV-017 — Ingress operational bookkeeping distinct from authoritative history (blocked — no public failure injection)

- **Stable CV ID:** `CV-017`
- **Clause:** `world-runtime.md` §2.2 vs §2.5 vs §2.6; `m8/t2` Ingress platform lifecycle; `loom-api::IngressStatus`.
- **Preconditions:** N/A — blocked. Planned precondition would be: Ingress `Accepted` then platform `Retryable(IngressTechnicalFailure)` before terminal completion. Current `crates/loom-api`/`loom-client`/`loom-boundary` has no public API to inject or observe `IngressTechnicalFailure` via controlled harness (`IngressService` only exposes `submit_ingress` and `ingress_status`; no fault-injection API exists).
- **Formal Surface:** Blocked: `IngressService::ingress_status(IngressId) -> IngressStatusRecord { status: IngressStatus::Retryable(IngressTechnicalFailure) }` observation has no public/controlled injection path; `HistoryService::list_events` + `QueryService::get_facet` authority check exists but transition `Accepted/Processing -> Retryable -> Completed` cannot be driven via public surface. No fault-injection or equivalent controlled fixture exists in repo.
- **Expected Result:** Blocked: Intent is `Retryable` does not create Event and `Accepted/Retryable -> Completed(IngressCompletion::Committed { event_refs, timeline_version })` creates exactly one `EventRef` without duplicates; `IngressStatus::Retryable` never rendered as `Completed(Rejected)`. Current contract provides no public way to force `Retryable` and then observe recovery — explicit gap, requires Architecture Amendment adding public/controlled Ingress failure injection/observation before Validator coverage. Marked `BLOCKED` per Stop Conditions.
- **Evidence Classes:** blocked (no public/controlled fault-injection surface)
- **PostgreSQL Live Mandatory:** No — blocked (no public/controlled fault-injection surface to drive PostgreSQL proof)
- **Owner:** T11
- **Complementary:** `m8/t2` status vs history table separation; `m8/t3` recovery not inventing truth — internal, not public Validator evidence.
- **Unsuitable Reason:** No public fault-injection surface; `IngressService` only exposes `submit_ingress`/`ingress_status`, no `Retryable` injection — explicit gap, requires Architecture Amendment adding public fault-injection API before Validator coverage. Marked blocked per Stop Conditions.

### CV-018 — Single-Timeline logical head ordering (blocked — no public Work schedule/claim)

- **Stable CV ID:** `CV-018`
- **Clause:** `world-runtime.md` §8.3-§8.4 Deterministic logical Work order, Head-of-line rule; `runtime-contracts.md` §14; `m5/t4` head-aware scheduler claim.
- **Preconditions:** N/A — blocked. Planned: Timeline at `WorldInstant T20`, two `WorkId` with same `effective_due_world_time=T20` but distinct `logical_schedule_order` (0,1) would be scheduled via `WorkMutation`. Current `loom-api` only exposes `AdminService::schedule_agency_wake` (agency wake scheduling, fields `target, expected_version, work_id, agent, cognition, payload, schedule`) and `AdminService::timeline_logical_status(target)` read; there is no public `schedule_work` or `claim_work` API for generic Work scheduling via `loom-api`/`loom-client` or controlled harness.
- **Formal Surface:** Blocked for schedule/claim: `AdminService::schedule_agency_wake` is agency scheduling only, not generic Work head ordering; `ActionService` does not expose Work. Observation via `TimelineService::inspect_timeline` + `AdminService::timeline_logical_status` + `HistoryService::list_events` exists but driving two Works has no public invocation surface.
- **Expected Result:** Blocked: Intent is head `(T20,0)` is only `claimable` and history commits in `head→next` order. Current contract provides no public way to schedule and claim two generic Works via `loom-api` — explicit gap requiring public scheduler Work API before Validator coverage. Marked `BLOCKED` per Stop Conditions.
- **Evidence Classes:** blocked (no public/controlled schedule/claim surface)
- **PostgreSQL Live Mandatory:** No — blocked (no public/controlled schedule/claim surface to drive PostgreSQL proof)
- **Owner:** T12 (#317)
- **Complementary:** `m5/t4` claim with `SKIP LOCKED` head-only; `loom-storage/tests/postgres_work.rs` ordering — internal, not public Validator evidence.
- **Unsuitable Reason:** No public `schedule_work`/`claim_work` API exists; `schedule_agency_wake` cannot prove generic Work head-only ordering — explicit gap, requires public scheduler Work API before Validator coverage. Marked blocked per Stop Conditions.

### CV-019 — Stale fencing / ownership cannot commit after authority moved (blocked — no public fence injection)

- **Stable CV ID:** `CV-019`
- **Clause:** `world-runtime.md` §8.1 Semantic due vs operational claimability; `runtime-contracts.md` §14 claim/admission; `implementation.md` §13.3 `SKIP LOCKED` scope; `m5/t4`.
- **Preconditions:** N/A — blocked. Planned: head Work `work_id` with `lease`/`fence` generation `g1` would be injected via `claim` with `expected_version` CAS, then stale `complete`. Current `loom-api` only exposes `AdminService::terminalize_work(AdminTerminalizeWorkRequest { target, work_id, expected_version, terminal_state })` for termination and `AdminService::timeline_logical_status(target)` for read; there is no public `claim_work` or fence token injection API via `loom-api`/`loom-client` or controlled harness.
- **Formal Surface:** Blocked for claim: `AdminService::terminalize_work` is termination only (fields `target, work_id, expected_version, terminal_state`), not stale `claim`/`complete`. Observation via `TimelineService::inspect_timeline(TimelineTarget) -> TimelineSnapshot { version }` and `HistoryService::list_events` for winner's Event, but `claim`/`fence` injection has no public invocation surface.
- **Expected Result:** Blocked: Intent is stale `complete` returns `ApiErrorCode::Conflict` (stale fence) and history contains only winner's `CommittedEvent`. Current contract provides no public way to inject `lease`/`fence` generation via `loom-api` — explicit gap requiring public scheduler fence injection API before Validator coverage. Marked `BLOCKED` per Stop Conditions.
- **Evidence Classes:** blocked (no public/controlled fence surface)
- **PostgreSQL Live Mandatory:** No — blocked (no public/controlled fence surface to drive PostgreSQL proof)
- **Owner:** T12
- **Complementary:** `loom-storage/tests/postgres_work_stale_completion.rs`; `m5/t4` fence.
- **Unsuitable Reason:** No public `claim`/`fence` injection API; `terminalize_work` is termination only — explicit gap, requires public fence injection API before Validator coverage. Marked blocked per Stop Conditions.

### CV-020 — Independent Timelines not globally serialized

- **Stable CV ID:** `CV-020`
- **Clause:** `world-runtime.md` §8.9 Scope, §8.4 head-of-line per Timeline; `m5/t4` timeline isolation.
- **Preconditions:** Two independent Worlds/Timelines `A` and `B` (or fork siblings) each with one due Pending Work.
- **Formal Surface:** `WorldService::create_world_from_template(CreateWorldFromTemplateRequest)` (two Worlds) or `TimelineService::fork(ForkTimelineRequest::new)` (sibling), then `AdminService::schedule_agency_wake(AdminScheduleAgencyWakeRequest { target, expected_version, work_id, agent, cognition, payload, schedule: WorkSchedule::At(WorldInstant) })` to create due `Pending` Works `work_id` with `effective_due=T`, plus `ActionService::invoke` per Timeline if Reaction-based Work creation is used (existing `neutral.counter` Reaction registered), `HistoryService::list_events` per Timeline + `AdminService::timeline_logical_status` for `works` isolation check.
- **Expected Result:** `invoke` on Timeline B commits while Timeline A's head remains Pending; no cross-Timeline `WorldTime advancement forbidden` due to sibling due work; each Timeline's `inspect_timeline` version increments independently.
- **Evidence Classes:** External, controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** No.
- **Owner:** T12
- **Complementary:** `m5` scheduler topology; `m6/t5` fork ancestry isolation.
- **Unsuitable Reason:** —

### CV-021 — Explicit World Time advance via authority path

- **Stable CV ID:** `CV-021`
- **Clause:** `world-runtime.md` §6 World Time is Timeline logical state, §6.3 explicit advancement, §8.7 Time advancement policy; `runtime-contracts.md` §2.2; `m5/t5` time driver.
- **Preconditions:** Timeline quiescent (no Pending Work). `TimelineSnapshot.world_time == WorldInstant(T10)` and `TimelineSnapshot.version == TimelineVersion { head_event_seq, state_revision }` known.
- **Formal Surface:** `AdminService::advance_world_time(AdminAdvanceWorldTimeRequest { target, expected_version, current: WorldInstant(T10), next: WorldInstant(T20) })` + `TimelineService::inspect_timeline`.
- **Expected Result:** `advance_world_time` returns `Ok(AdminAdvanceWorldTimeResult { target, from: WorldInstant(T10), to: WorldInstant(T20), version: TimelineVersion })` where `version.state_revision` incremented by 1 vs input; `inspect_timeline.world_time == WorldInstant(T20)` and `inspect_timeline.version == result.version`. No fake Event created (`list_events` count unchanged). Replay after restart shows same `world_time`.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** No.
- **Owner:** T13 (#318)
- **Complementary:** `m5/t5` driver CAS; `loom-storage` timeline logical journal.
- **Unsuitable Reason:** —

### CV-022 — Due Work blocks invalid time advancement (quiescence barrier)

- **Stable CV ID:** `CV-022`
- **Clause:** `world-runtime.md` §8.5 Due-work quiescence barrier, §6.3 rule 8, §8.8 auto-advance safety; `m5/t5`.
- **Preconditions:** Timeline at T20 with due Pending Work `W1 (effective_due=T20)` in retry/backoff operationally unclaimable (`available_at > PlatformTime` or missing implementation).
- **Formal Surface:** `AdminService::advance_world_time(AdminAdvanceWorldTimeRequest { target, expected_version, current: WorldInstant(T20), next: WorldInstant(T30) }) -> AdminAdvanceWorldTimeResult { target, from, to, version }` attempt `T20→T30`, `AdminService::timeline_logical_status(TimelineTarget) -> AdminTimelineLogicalStatus { works: Vec<AdminLogicalWorkStatus>, chronology_budget, version, world_time }` for `works`/`chronology_budget` observation, `TimelineService::inspect_timeline` for `world_time`/`version`.
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
- **Formal Surface:** `HistoryService::list_events(EventQuery::all(target)) -> Vec<CommittedEvent>`, `HistoryService::list_events_page(EventQuery::all(target)) -> EventPage { events: Vec<CommittedEvent>, next_after: Option<EventSeq> }` paging, `TimelineService::inspect_timeline(TimelineTarget) -> TimelineSnapshot { version, world_time, ancestry }` (`ancestry`, `world_time`, `version`), `AdminService::timeline_logical_status(TimelineTarget) -> AdminTimelineLogicalStatus { works: Vec<AdminLogicalWorkStatus>, version, world_time }` for work `logical_schedule_order`, `QueryService::get_facet` for materialized state.
- **Expected Result:** After restart/new `LoomClient`, `list_events` order by `EventSeq` equals pre-restart; `inspect_timeline` `world_time`, `version.state_revision`, and work logical order identical; not derived from `max(event.occurred_at)` or `PostgreSQL natural row order` or `available_at`.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL, controlled restart (`BackendContext::restart()` + `RestartCapability::ControlledBoundaryRestart`).
- **PostgreSQL Live Mandatory:** Yes.
- **Owner:** T13
- **Complementary:** `m6/t1-t5` replay; `loom-storage/tests/postgres_restart_resume.rs`.
- **Unsuitable Reason:** —

### CV-024 — Reaction atomicity with triggering commit

- **Stable CV ID:** `CV-024`
- **Clause:** `runtime-contracts.md` §5.7 Reaction Registration, `core.md` §6 Direct Effect vs downstream Reaction, `world-runtime.md` §8.3 last paragraph; `m5/t6` reaction atomic scheduling.
- **Preconditions:** Capability `neutral.counter` with `Reaction` registered for `EventType "neutral.counter.incremented"` that schedules Immediate Work `neutral.counter.increment_work` (existing fixture `neutral.counter` Reaction).
- **Formal Surface:** `ActionService::invoke(ActionRequest) -> ExecutionResult::Committed { event_ids, timeline_version }` (seed `neutral.counter.seed` with `Reaction` `neutral.counter.increment_work` registered), `HistoryService::list_events(EventQuery) -> Vec<CommittedEvent>` + `HistoryService::list_events_page(EventQuery) -> EventPage { events, next_after }` for `EventSeq` order, `TimelineService::inspect_timeline` for `version`, `AdminService::timeline_logical_status(TimelineTarget) -> AdminTimelineLogicalStatus { works, version }` for reaction `Pending` Work `effective_due_world_time`/`logical_schedule_order` observation.
- **Expected Result:** Triggering `CommittedEvent { event_type: EventTypeId("neutral.counter.incremented") }` and `Reaction` `neutral.counter.increment_work` schedule share same `Logical Commit` (`TimelineVersion` increments once); `HistoryService::list_events` shows `incremented` Event, `AdminService::timeline_logical_status` shows `Pending` Work `neutral.counter.increment_work` with `effective_due_world_time` == trigger `occurred_at`; no half-state. Second `execute_work` produces separate `CommittedEvent`. `BackendContext::restart()` preserves both.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** No (atomicity logical; PostgreSQL validates durability).
- **Owner:** T13
- **Complementary:** `m5/t6` reaction atomic scheduling; `loom-runtime` reaction.
- **Unsuitable Reason:** —

### CV-025 — History/trajectory positive isolation - sibling leak excluded

- **Stable CV ID:** `CV-025`
- **Capability / Clause:** `m6/t5` History visibility after fork; `runtime-contracts.md` §9.1; `world-runtime.md` §3.
- **Preconditions:** World fork as in CV-007: parent seeded `value=5`, child fork A incremented to `15`, sibling B untouched. Entity fresh.
- **Formal Surface:** `HistoryService::list_events(EventQuery::all(target))`, `HistoryService::entity_trajectory(EntityTrajectoryQuery::all(target, entity_id)(target, entity_id))`, `TimelineService::inspect_timeline` for `ancestry`, `QueryService::get_facet(FacetQuery::new(target, owner, facet_type))` for facet isolation check.
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

### CV-028 — Semantic projection rebuildable, not authority (blocked — no public API)

- **Stable CV ID:** `CV-028`
- **Clause:** `m7/t2` semantic indexes + pgvector, `m7/t3` mediator, `implementation.md` placeholder for vector.
- **Preconditions:** N/A — blocked. Planned precondition would be: committed Events with `neutral.counter.seed` 3 times; semantic index `neutral.counter.projector@1` built via Runtime projection. No public API exists to trigger build/rebuild/delete/query.
- **Formal Surface:** Blocked: `crates/loom-api/src/lib.rs` exposes `CatalogService::catalog` with `SemanticIndexDescriptor` metadata but no public `SemanticService` / `query_semantic_projection` / `rebuild_semantic_projection` / `delete_semantic_projection`; `crates/loom-client` also lacks such service. Authority is only `HistoryService::list_events` + `QueryService::get_facet`; projection observation has no public surface.
- **Expected Result:** Blocked: Validator cannot observe semantic projection rebuild via public surface. If projection existed, delete/rebuild would leave `list_events`/`get_facet` authority unchanged (per `m7/t2`), but current contract provides no way to perform or observe the operation via `loom-api` — must not invent alternative via internal `loom-storage` table.
- **Evidence Classes:** blocked (no public surface) — no External/InMemory/PostgreSQL evidence class applicable until API exists.
- **PostgreSQL Live Mandatory:** No — blocked.
- **Owner:** T15 (#320)
- **Complementary:** `m7/t2` pgvector add/rebuild leaves authority unchanged; `m7/t3` read not authority — internal evidence, not public Validator evidence.
- **Unsuitable Reason:** No public SemanticService/semantic projection rebuild/delete/query API exists in current `loom-api` (only `SemanticIndexDescriptor` metadata via `CatalogService::catalog`); capability-owned index cannot be validated via current public `loom-api`/`loom-client` — explicit gap, requires Architecture Amendment adding public semantic projection service before Validator coverage. Marked blocked per Stop Conditions.

### CV-029 — Blob/reference missing does not rewrite history (blocked — no public API)

- **Stable CV ID:** `CV-029`
- **Clause:** `m7/t4` immutable BlobStore; `implementation.md` blob.
- **Preconditions:** N/A — blocked. Planned precondition: Facet `neutral.doc@1` stores `BlobReference` (`BlobId`); Blob deleted or never uploaded.
- **Formal Surface:** Blocked: `crates/loom-api` exposes `FacetSnapshot.value` containing `BlobReference` (opaque JSON value via `QueryService::get_facet`) but no public `BlobService` / blob read API; `crates/loom-api/src/lib.rs` grep for `BlobService` returns 0 results; authority only `QueryService::get_facet` + `HistoryService::list_events`.
- **Expected Result:** Blocked: Validator can observe `FacetSnapshot.value` containing blob reference via `get_facet`, but cannot validate blob fetch failure via public surface — no public blob read to assert `Unavailable`/`NotFound`. If API existed, blob read failure would not alter `get_facet` payload nor `list_events` history, but current contract provides no public blob fetch.
- **Evidence Classes:** blocked (no public surface) — `get_facet` Facet value observation possible, but blob fetch evidence class N/A until API exists.
- **PostgreSQL Live Mandatory:** No — blocked.
- **Owner:** T15
- **Complementary:** `m7/t4` blob immutability; `loom-storage` blob tests — internal, not public Validator evidence.
- **Unsuitable Reason:** No public BlobService/blob read API exists in current `loom-api`; blob availability failure cannot be validated via current public surface — explicit gap, requires Architecture Amendment adding public blob service before Validator coverage. Marked blocked per Stop Conditions.

### CV-030 — Pinned/versioned read via fork at version (existing API)

- **Stable CV ID:** `CV-030`
- **Clause:** `amendment 0003 §4` pinned read consistency via `ForkTimelineRequest::at_version`; `runtime-contracts.md` §6.1-6.2; `m7/t5` scalable pinned reads (consistency, not full materialization).
- **Preconditions:** World at `TimelineVersion { head_event_seq: 10, state_revision: 100 }` with `counter=10` visible via `QueryService::get_facet`; then second commit `counter=11` at `head_event_seq: 11, state_revision: 101`.
- **Formal Surface:** `TimelineService::fork(ForkTimelineRequest::at_version(source: TimelineTarget, source_version: TimelineVersion{10,100}))` → `ForkTimelineResult (TimelineSnapshot)` fork_target, then `QueryService::get_facet(FacetQuery::new(fork_target, FacetOwner::entity(entity_id), FacetTypeId::from("neutral.counter.value")))` and `HistoryService::list_events(EventQuery::all(fork_target))` for history isolation; plus `TimelineService::inspect_timeline(fork_target)` for ancestry `fork_parent_version`.
- **Expected Result:** Fork target `get_facet` returns `Some(FacetSnapshot { value: {"value":10}})` (value at pinned version) even though head `get_facet` on original timeline returns `11`; `inspect_timeline(fork_target).ancestry.fork_parent_version == Some(TimelineVersion{10,100})`; `list_events(fork_target)` contains history up to `head_event_seq 10` only; no invented `get_facet_at_version`/`BaseWorldView`/`ResolutionContext` — path is existing `ForkTimelineRequest::at_version` + `get_facet`.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** Yes — pinned consistency must be persistent across restart; InMemory positive path suffices logically but certification requires at least one durable evidence.
- **Owner:** T15
- **Complementary:** `m7/t5` pinned reads via fork-at-version; amendment 0003 scalable reads consistency; core fork logic `m6/t5`.
- **Unsuitable Reason:** — (implementable via existing `ForkTimelineRequest::at_version` + `QueryService::get_facet`; no new API invented)

### CV-031 — Event→Session→Revision provenance retained after revision change

- **Stable CV ID:** `CV-031`
- **Clause:** `m9/t2` Session provenance, `m9/t3` Event↔Session linkage, `evolution.md`.
- **Preconditions:** Session S1 under R1 commits `E1` via `neutral.counter.seed`.
- **Formal Surface:** `ActionService::invoke` (produces S1) creates `ExecutionResult::Committed { event_ids, timeline_version }`; provenance via `AdminService::get_execution_session(AdminExecutionSessionRequest { session_id }) -> AdminExecutionSession` and `AdminService::session_for_event(EventRef) -> AdminEventSessionLookup`; no alternative via `TimelineSnapshot` provenance — `TimelineSnapshot` contains only `target, version, world_time, ancestry` (no provenance field). Validator uses `loom-client` + `AdminService` via `loom-boundary` admin routes with authorized context.
- **Expected Result:** `AdminService::session_for_event(EventRef(E1)) -> AdminEventSessionLookup { event_ref: EventRef(E1), session_id: Some(S1) }` succeeds even after `activate_runtime_revision(R2)`; `AdminService::get_execution_session(AdminExecutionSessionRequest { session_id: S1 }) -> AdminExecutionSession { id: S1, runtime_revision_id: R1, read_set: Vec<AdminReadDependency>, call_provenance: Vec<AdminResolutionCallEdge>, entropy_evidence: AdminEntropyEvidence }` shows `runtime_revision_id == R1`; `HistoryService::get_event(EventRef(E1)) -> CommittedEvent { id, timeline_id, sequence, event_type, schema_revision, occurred_at, payload, effects }` shows `CommittedEvent` history facts only (no `session_id`/`revision_id`/`read_set` — those are via Admin provenance). Reread of `E1` history remains `CommittedEvent` with same `sequence`/`payload`.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL, controlled restart.
- **PostgreSQL Live Mandatory:** Yes — provenance must survive durable restart (`PgStorage`).
- **Owner:** T16 (#321)
- **Complementary:** `m9/t3` atomic linkage; `m9/t2` provenance round-trip.
- **Unsuitable Reason:** —

### CV-032 — New Session after compatible R2 uses R2 without rewriting history

- **Stable CV ID:** `CV-032`
- **Clause:** `m9/t1` revision history, `m9/t5` upgrade gate, `world-runtime.md` §11.
- **Preconditions:** After R2 activation compatible with Binding, new Timeline action via Session S2.
- **Formal Surface:** `AdminService::activate_runtime_revision(AdminActivateRuntimeRevisionRequest)`, `ActionService::invoke(ActionRequest)` → `ExecutionResult::Committed`, `HistoryService::list_events(EventQuery)`/`get_event(EventRef)`, `AdminService::session_for_event(EventRef) -> AdminEventSessionLookup { session_id: Option<ExecutionSessionId> }` + `AdminService::get_execution_session(AdminExecutionSessionRequest { session_id }) -> AdminExecutionSession { runtime_revision_id }`.
- **Expected Result:** `AdminService::session_for_event(EventRef(E2)) == S2` and `AdminService::get_execution_session(AdminExecutionSessionRequest { session_id: S2 }).runtime_revision_id == R2`; `HistoryService::list_events`/`get_event` history shows `CommittedEvent` for `E2`; reread of `E1` via `get_event` still `CommittedEvent` with same `sequence`, provenance via `session_for_event(E1) == S1` and `get_execution_session(S1).runtime_revision_id == R1`. No running Session switches implementation mid-flight.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** Yes (new Session persistence).
- **Owner:** T16
- **Complementary:** `m9/t5` R1→R2 session switch; `loom-storage` `postgres_revision`.
- **Unsuitable Reason:** —

### CV-033 — Implementation/read/call/entropy provenance tied to committed execution

- **Stable CV ID:** `CV-033`
- **Clause:** `m9/t2` ReadSet/call graph/entropy, `runtime-contracts.md` §7.
- **Preconditions:** Session S1 with `read_set: Vec<AdminReadDependency>` containing `entity_facet` read and `entropy_evidence: AdminEntropyEvidence` sample and `call_provenance: Vec<AdminResolutionCallEdge>` (counter increment reads dependency). Registry at `counter 1.7.3` during S1; later registry updated to `1.8.0` still compatible.
- **Formal Surface:** `AdminService::get_execution_session(AdminExecutionSessionRequest { session_id }) -> AdminExecutionSession { runtime_revision_id: String, read_set: Vec<AdminReadDependency>, call_provenance: Vec<AdminResolutionCallEdge>, entropy_evidence: AdminEntropyEvidence }` (plus `cognitive_evidence: AdminCognitiveEvidence` for agency wakes) + `AdminService::get_runtime_revision(AdminRuntimeRevisionRequest { revision_id: String }) -> AdminRuntimeRevision { revision_id, capabilities: Vec<AdminRuntimeRevisionCapability { implementation_id: String, version: String }> }` for version check; `AdminReadDependency::Facet { owner: FacetOwner, facet_type: FacetTypeId, schema_revision: SchemaRevision }` shape.
- **Expected Result:** After new registry, `get_execution_session(S1).runtime_revision_id == "R1"` and `get_runtime_revision(AdminRuntimeRevisionRequest { revision_id: R1 }).capabilities[0].version == "1.7.3"` remain at commit time, not `1.8.0`; `get_execution_session(S1).read_set` (`Vec<AdminReadDependency::Facet { owner, facet_type, schema_revision }>`), `call_provenance` and `entropy_evidence` remain stable and not resampled on replay; `CommittedEvent` history via `HistoryService::list_events` does not contain revision (revision only via Admin provenance).
- **Evidence Classes:** controlled PostgreSQL (durable), controlled InMemory (logical).
- **PostgreSQL Live Mandatory:** Yes (controlled PostgreSQL persistence for durable provenance via `get_execution_session` + `get_runtime_revision`)
- **Owner:** T16
- **Complementary:** `m9/t2` provenance evidence; `loom-runtime` entropy.
- **Unsuitable Reason:** —

### CV-034 — Agency NoAction completes wake without fabricating Event (blocked — no cognitive injection seam)

- **Stable CV ID:** `CV-034`
- **Clause:** `m10/t4` Atomic Agency Wake Decision/Action commit, NoAction path; `amendment 0003 §3`.
- **Preconditions:** N/A — blocked. Planned: `AgencyWake` `work_id` with `cognition: String` would determine `Decision::NoAction`. Current `AdminScheduleAgencyWakeRequest.cognition: String` is stable requirement, not `Decision` injection; `Runtime::with_cognitive_executor(DeterministicCognitiveExecutor)` is application composition, not Validator `BackendHarness` seam; `AdminService::schedule_agency_wake` only creates `Pending` Work, does not execute Wake — no public/controlled cognitive-injection + Work-execution surface in `loom-api`/`loom-client`/`BackendHarness`.
- **Formal Surface:** Blocked: `AdminService::schedule_agency_wake(AdminScheduleAgencyWakeRequest { target, expected_version, work_id, agent, cognition, payload, schedule })` only creates `Pending` Work; no `Runtime::execute_work(target, work_id, now, claimed_until, retry_available_at)` or deterministic `CognitiveExecutor` injection via `BackendHarness`. Observation via `AdminService::timeline_logical_status` + `HistoryService::list_events` exists but driving `NoAction` to `Completed` has no public seam.
- **Expected Result:** Blocked: Intent is `Pending→Completed` with no `CommittedEvent`. Current Validator has no `with_cognitive_executor` + `execute_work` seam to drive `NoAction` to `Completed` via public surface — explicit gap, requires public cognitive-injection + Work-execution API. Marked `BLOCKED` per Stop Conditions.
- **Evidence Classes:** blocked (no public/controlled cognitive-injection + Work-execution surface)
- **PostgreSQL Live Mandatory:** No — blocked
- **Owner:** T17 (#322)
- **Complementary:** `m10/t4` NoAction atomic; `loom-agency` contracts — internal, not public Validator evidence.
- **Unsuitable Reason:** `AdminScheduleAgencyWakeRequest.cognition: String` is not `Decision` provider; `Runtime::with_cognitive_executor` is app composition, `schedule_agency_wake` only creates `Pending` — no public/controlled seam to inject deterministic `CognitiveExecutor` and drive Wake to `Completed` via `execute_work` — explicit gap, requires public Agency execution API. Marked blocked per Stop Conditions.

### CV-035 — Agency Act enters normal Action authority path (blocked — no cognitive injection seam)

- **Stable CV ID:** `CV-035`
- **Clause:** `m10/t4` Act via normal path; `runtime-contracts.md` §8 Agency Decision.
- **Preconditions:** N/A — blocked. Planned: same `work_id` with `Decision::Act(ActionInvocation::new("neutral.counter.increment", json!({amount:1})))` via deterministic `CognitiveExecutor`. Current `cognition: String` is not `Decision` injection; `with_cognitive_executor` is app composition, `schedule_agency_wake` only creates `Pending`.
- **Formal Surface:** Blocked: `AdminService::schedule_agency_wake` only creates `Pending`; no `Runtime::execute_work` + `DeterministicCognitiveExecutor` seam. Observation via `AdminService::timeline_logical_status` + `HistoryService::list_events` exists but driving `Act` to `Committed` has no public seam.
- **Expected Result:** Blocked: Intent is `Act` shares atomic `Logical Commit` (`TimelineVersion` increments once) and `list_events` gains one `EventId`. No public seam to drive `Act` via `execute_work` — explicit gap, requires public Agency execution API. Marked `BLOCKED` per Stop Conditions.
- **Evidence Classes:** blocked (no public/controlled cognitive-injection + Work-execution surface)
- **PostgreSQL Live Mandatory:** No — blocked
- **Owner:** T17
- **Complementary:** `m10/t4` Act via normal path — internal, not public Validator evidence.
- **Unsuitable Reason:** No public cognitive-injection + Work-execution surface; `cognition` String is not `Decision` — explicit gap, requires public Agency execution API. Marked blocked per Stop Conditions.

### CV-036 — Agency semantic rejection produces no false Event (blocked — no cognitive injection seam)

- **Stable CV ID:** `CV-036`
- **Clause:** `m10/t4` R-1 semantic Rejected MUST complete Wake as determined no-world-change; `runtime-contracts.md` §5.4 Rejected.
- **Preconditions:** N/A — blocked. Planned: `Act` with invalid payload (e.g., `amount: "bad-type"`) would be `Rejected` via `CognitiveExecutor` `Decision::Act` -> `ExecutionResult::Rejected`. Current `schedule_agency_wake` only creates `Pending`, no `execute_work` seam.
- **Formal Surface:** Blocked: `AdminService::schedule_agency_wake` only creates `Pending`; no `execute_work` seam. Observation via `HistoryService::list_events` exists but driving `Rejected` has no public seam.
- **Expected Result:** Blocked: Intent is `Rejected` completes `Pending→Completed` with no `Event`, distinct from `Retryable`. No public seam to drive `Rejected` via `execute_work` — explicit gap, requires public Agency execution API. Marked `BLOCKED` per Stop Conditions.
- **Evidence Classes:** blocked (no public/controlled cognitive-injection + Work-execution surface)
- **PostgreSQL Live Mandatory:** No — blocked
- **Owner:** T17
- **Complementary:** `m10/t4` R-1; `loom-runtime` rejected path — internal, not public Validator evidence.
- **Unsuitable Reason:** No public cognitive-injection + Work-execution surface; `ExecutionResult::Rejected` cannot be observed via `schedule_agency_wake` alone — explicit gap, requires public Agency execution API. Marked blocked per Stop Conditions.

### CV-037 — Concurrent/stale CAS loser cannot overwrite winner; provenance records path (blocked — no public claim API)

- **Stable CV ID:** `CV-037`
- **Clause:** `m10/t5` Agency Wake scheduling CAS policy, resample vs reuse; `world-runtime.md` §8.1; `runtime-contracts.md` §7.3.
- **Preconditions:** N/A — blocked for claim portion. Planned: same logical head Wake `work_id` would be claimed by two workers with stale/new `TimelineVersion`/fence (`expected_version` CAS). Current `loom-api` only exposes `AdminService::schedule_agency_wake(AdminScheduleAgencyWakeRequest)` for scheduling and `AdminService::timeline_logical_status(target) -> AdminTimelineLogicalStatus` for read; there is no public `claim_work`/`execute_work` API — claim is internal scheduler (`loom-runtime`) not exposed via `loom-api`/`loom-client` or controlled harness.
- **Formal Surface:** Blocked for claim: `AdminService::schedule_agency_wake` is scheduling only (fields `target, expected_version, work_id, agent, cognition, payload, schedule`), not concurrent claim/execute. Observation via `TimelineService::inspect_timeline(TimelineTarget) -> TimelineSnapshot { version }` and `HistoryService::list_events` for winner's Event, and `AdminService::get_execution_session` for `discarded` metadata, but concurrent `CAS` conflict has no public invocation surface in current `crates/loom-api`.
- **Expected Result:** Blocked: Intent is exactly one winner's `Logical Commit` (`AdminTimelineLogicalStatus` `work_id` + `TimelineVersion` CAS succeeds), loser receives `ApiErrorCode::Conflict` (stale `expected_version`), history contains winner's `CommittedEvent` only once, provenance shows `resample` with discarded cognition cost. Current contract provides no public way to invoke concurrent claim via `loom-api` — explicit gap requiring public scheduler claim API before Validator coverage. Marked `BLOCKED` per Stop Conditions.
- **Evidence Classes:** blocked (no public/controlled claim surface)
- **PostgreSQL Live Mandatory:** No — blocked (no public/controlled claim surface to drive PostgreSQL proof)
- **Owner:** T17
- **Complementary:** `m10/t5` stale CAS; `loom-storage/tests/postgres_work_stale_completion.rs` — internal, not public Validator evidence.
- **Unsuitable Reason:** No public `claim_work`/`fence` injection API; `schedule_agency_wake` is scheduling only — explicit gap, requires public scheduler claim API before Validator coverage. Marked blocked per Stop Conditions.

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
- **Formal Surface:** `SubscriptionService::subscribe(SubscriptionRequest::resume(target, cursor, limit))` with `cursor=ChangeFeedCursor::after(target, 5)` and `ChangeFeedPage.next_cursor: Option<ChangeFeedCursor>` (only when `page.next_cursor == Some(cursor)` use `resume`).
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
- **Formal Surface:** `SubscriptionService::subscribe(SubscriptionRequest::new(target, limit))` → disconnect (client sees `SubscriptionResult::Backpressure` or `ApiError`) → `SubscriptionService::subscribe(SubscriptionRequest::resume(target, cursor, limit))` where `cursor` is prior `ChangeFeedPage.next_cursor: Option<ChangeFeedCursor>` `Some(cursor)`, `HistoryService::list_events` for authority; `SubscriptionResult` is `Events(ChangeFeedPage)` or `Backpressure` variant.
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

- `Yes`: CV-014, CV-016, CV-022, CV-023, CV-030, CV-031, CV-032, CV-033, CV-039, CV-040 (10 rows). Rationale in per-row table. `No — blocked`: CV-017, CV-018, CV-019, CV-028, CV-029, CV-034, CV-035, CV-036, CV-037 (9 rows) — no public/controlled Agency/scheduler/fault-injection surface to drive PostgreSQL proof.
- `No`: remaining 10 rows validate logical semantics even without live PG; they still exercise PG path when available but remain pass via controlled InMemory.

Certification gate T20 (#325) proves real controlled PostgreSQL live evidence and rejects `skipped`/`unavailable`/fake-PG results (`VALR-T06`).

## Complementary Core / M13 Evidence and Why It Does Not Replace Validator

Validator is public-consumer evidence (`loom-client` / `loom-api` formal surfaces). Internal core/storage tests remain complementary, never sole evidence:

- `m4/t2` binding, `m5/t4` scheduler, `m6/t5` ancestry, `m7` query/semantic/blob/pinned, `m8` Ingress/feed, `m9` provenance, `m10` Agency, plus `loom-storage/tests/postgres_*` persistence contracts.
- M13-T1 closure audit: `loom-validation-candidate` profile passed required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, deny, capacity gates at merge `19c797d`.
- For each CV row, Validator scenario must be implemented on top of existing authority and observed via public API; internal test pass cannot be cited as `Pass` for that CV's public coverage.

## Coverage Gaps Explicitly Recorded (not hidden)

1. **Same-Timeline historical materialization** — `ForkTimelineRequest::at_version` is supported replay; direct same-Timeline historical materialization is not a public operation. Recorded in CV-005 gap and reused for CV-023/025. Validator reports `Unavailable` with `finding:gap:same-timeline-historical-materialization-is-not-a-public-operation` controlled harness via `BackendContext::restart()` + `RestartCapability::ControlledBoundaryRestart`.
2. **InMemory durable restart** — `CV-009`-class ephemeral InMemory store; controlled PostgreSQL restart is sole durability evidence for `CV-014/023/031/040` etc. InMemory `CV-009` unavailable is expected gap.
3. **Global total ordering of all root inputs** — `world-runtime.md` §8.9: v0 freezes Scheduler-managed Work ordering + World Time barrier, not a global total order over external Action/Ingress/Operator inputs. Validator does not claim such ordering.
4. **Fine-grained ReadSet validation beyond v0 CAS** — `runtime-contracts.md` §7 sequencing is Timeline-wide via `TimelineVersion` CAS in v0; read-set-based concurrency remains deferred (docs/architecture/README.md §4).
5. **Large-World benchmark thresholds** — measured capacity envelope in `docs/capacity-envelope.md`; larger-scale claims marked unproven.
6. **Dynamic per-World Capability hot-plug** — `world-runtime.md` §3.4 v0 immutability; Validator does not cover hot-plug (future architecture review required).
7. **Historical replay checkpoint acceleration** — deferred; `replay` correctness proven via `CV-023` without snapshot optimization.
8. **Semantic projection rebuild (CV-028 blocked)** — no public `SemanticService` / semantic projection rebuild/delete/query API exists in `crates/loom-api` / `crates/loom-client`; only `SemanticIndexDescriptor` metadata via `CatalogService::catalog`. Current contract provides no way to create or observe projection via `loom-api`; Validator cannot implement `CV-028` via public surface — explicit gap, requires Architecture Amendment adding public semantic projection service. Marked `blocked` per Stop Conditions; evidence class `blocked (no public surface)`.
9. **Blob reference fetch (CV-029 blocked)** — no public `BlobService` / blob read API exists; `FacetSnapshot.value` may contain opaque `BlobReference` but fetch cannot be observed via `loom-api`. `CV-029` blocked — explicit gap requiring public blob service Amendment.
10. **Pinned read inventing API (CV-030 corrected)** — previous draft invented `get_facet_at_version`/`BaseWorldView`/`ResolutionContext`; corrected to existing `TimelineService::fork(ForkTimelineRequest::at_version)` + `QueryService::get_facet` on fork target. `CV-030` remains implementable via this existing path; `CV-028/029` remain blocked.
11. **Ingress failure injection (CV-017 blocked)** — no public fault-injection or `Retryable` injection API exists; `IngressService` only exposes `submit_ingress`/`ingress_status`. `CV-017` `Retryable(IngressTechnicalFailure)` observation cannot be driven via public surface — explicit gap, requires Ingress failure injection API.
12. **Concurrent scheduler claim (CV-037 blocked)** — no public `claim_work`/`execute_work` API; `AdminService::schedule_agency_wake` is scheduling only, and `timeline_logical_status` is read-only. Concurrent `CAS`/fence claim cannot be invoked via `loom-api` — explicit gap, requires public scheduler claim API.
13. **Stale fence injection (CV-019 blocked)** — no public `claim`/`fence` token injection API; `AdminService::terminalize_work` is termination only. `CV-019` stale `complete` cannot be driven via public surface — explicit gap, requires public fence injection API.
14. **Scheduler head ordering (CV-018 blocked)** — no public `schedule_work`/`claim_work` API; `AdminService::schedule_agency_wake` is agency scheduling only, `timeline_logical_status` is read-only. `CV-018` head `(T20,0)` claimability cannot be driven via public surface — explicit gap, requires public scheduler Work API.
15. **Agency NoAction/Act/Rejected execution (CV-034/035/036 blocked)** — `AdminScheduleAgencyWakeRequest.cognition: String` is not `Decision` injection; `Runtime::with_cognitive_executor(DeterministicCognitiveExecutor)` is app composition, not Validator `BackendHarness` seam; `AdminService::schedule_agency_wake` only creates `Pending` Work, not execute. `CV-034` `NoAction`, `CV-035` `Act`, `CV-036` `Rejected` have no public/controlled cognitive-injection + `Runtime::execute_work(target, work_id, now, claimed_until, retry_available_at)` seam — explicit gap, requires public Agency execution API.
16. **Concurrent Agency claim (CV-037 blocked)** — already listed as 12, but keep for Agency grouping; see 12.
17. **Agency provenance via Agency execution (CV-034-037)** — `ExecutionResult::Rejected` and `NoAction` completion cannot be observed via `schedule_agency_wake` alone; requires `execute_work` + `timeline_logical_status` + `get_execution_session`/`session_for_event`.

No new capability scenario invented beyond T10–T18 intents above; any additional need requires Architecture Amendment before coverage claim.

## Stop Conditions / Blocked Rows

- If a required scenario cannot be specified without a new authority/semantic decision, mark that matrix row `blocked` and escalate. Do not invent the missing architecture in T08.
- At freeze, 9 rows are blocked under current `docs/architecture/` + accepted Amendments `0001-0003` authority: `CV-017` (Ingress), `CV-018` (scheduler), `CV-019` (fence), `CV-028` (semantic), `CV-029` (blob), `CV-034` (Agency NoAction), `CV-035` (Agency Act), `CV-036` (Agency Rejected) and `CV-037` (concurrent claim) — no public/controlled Agency execution or scheduler injection API exists (see detailed sections and Coverage Gaps 8/9/11/12/13/14/15/16/17). `CV-030` remains implementable via `ForkTimelineRequest::at_version` + `get_facet`. All other rows are implementable via existing `loom-api` surfaces: `WorldService`, `ActionService`, `IngressService`, `TimelineService`, `QueryService`, `HistoryService`, `CatalogService`, `SubscriptionService`, `AdminService` (`get_execution_session`, `session_for_event`, `get_runtime_revision`, `timeline_logical_status`, `terminalize_work`, `advance_world_time` with `from`/`to`/`version`).
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
- [x] Matrix identifies explicit coverage gaps rather than hiding them (Coverage Gaps section, 17 items, 9 blocked CV-017/018/019/028/029/034/035/036/037).
- [ ] Reviewer confirms the matrix is implementable without semantic guesswork (pending independent Reviewer).
- [ ] CI/docs checks complete before marking completed (pending CI).

## Progress Log

- 2026-08-27 — Created `docs/tasks/validator-recert/stage-2/t08-coverage-matrix.md` as contract-only leaf with `status: in_progress`, `depends_on: [312]`, empty `completed_at`/`completion_pr`/`merge_sha`. Froze `CV-012..CV-040` allocation with no conflict (production registry at `d4437fb` contains `CV-001..CV-011`; `CV-012` in `reports.rs` test helpers is not a production registration). Specified per-scenario capability clause, preconditions/fixtures, formal `loom-api` surfaces (`WorldService`/`ActionService`/`IngressService`/`TimelineService`/`QueryService`/`HistoryService`/`CatalogService`/`SubscriptionService`/`AdminService`), expected results, evidence classes, PostgreSQL mandatory flags, owners, complementary core/M13 evidence, and unsuitable reasons. Ensured parallel-safe suite ownership for T09 and escalatable blocked marking. Noted cross-stage `validator_ready` nuance: `--root stage-2` isolated check cannot resolve dependency `312` (lives under `stage-1`); canonical combined `--root docs/tasks/validator-recert` validates correctly. No production code, registry, or T01–T07 files modified.
