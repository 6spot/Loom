---
task: VALR-T08
issue: 313
status: completed
depends_on: [312]
created_at: 2026-08-26
started_at: 2026-08-27
completed_at: 2026-08-26
completion_pr: 343
merge_sha: 276981290b4d4b8b8d0299402944c5f75cbb9a69
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

## Evidence Policy and Correction Audit (effective contract)

This section is the effective evidence contract for the correction recorded in
this ledger. It supersedes the pre-policy suitability wording below for the
current candidate only; it does not rewrite the historical candidate or its
completion facts.

The Validator contract has three deliberately separate layers:

1. **Test-only driver** — a controlled fixture may use the existing
   `Runtime`, `WorkStore`, `Scheduler`, `Storage`/restart seam, and deterministic
   `CognitiveExecutor` to set up or control failure, Work, claim/fence,
   projection/blob, competitor, and recovery boundaries. This layer is setup
   and control only. It is not acceptance evidence and does not add a
   production API.
2. **Public observable evidence** — every `Pass`, `Fail`, or `Unavailable`
   conclusion is obtained through a `LoomClient` formal read/observation
   surface: `HistoryService`, `QueryService`, `IngressService`,
   `AdminService::timeline_logical_status`, session/provenance reads, or the
   existing Facet/blob/reference surfaces. Internal state and SQL are never
   Validator assertions.
3. **Product API / architecture gap** — a row is an architecture/semantic gap
   only when the Runtime authority or semantic contract itself is absent, the
   existing controlled fixture cannot drive it, and no existing formal read
   can observe it. A missing production-consumer creation/injection API alone
   is not a gap when the controlled driver and public observation already
   exist.

The hard constraints remain: direct SQL/internal-storage reads cannot be
acceptance evidence, and an unexecuted, fabricated, or internal-only result
cannot be reported as `Pass`. If a required driver or public observable state
is genuinely absent, the row remains `blocked` and names the missing Runtime
authority/semantic; the contract must not reverse this into a product-API
requirement.

### Historical candidate / pre-policy record (append-only)

The prior candidate was recorded on 2026-08-27 using the pre-policy rule that
treated missing production-facing injection APIs as architecture blockers. Its
reported result was **31 suitable / 9 blocked** across `CV-001..CV-040`.
That result, the nine blocked records and their evidence wording are historical
only. The original ledger front matter and completion facts remain unchanged:
`completion_pr: 343`, `merge_sha:
276981290b4d4b8b8d0299402944c5f75cbb9a69`; the prior candidate was based on
the pre-policy `d4437fbd332c8e6cac78c3093e0c26f33e8b448b` audit and merged
historical PR #343.

For auditability, the blocked records retained from that candidate are:

| CV | Historical pre-policy blocked record (evidence and unsuitable reason) |
| --- | --- |
| CV-017 | `blocked (no public/controlled fault-injection surface)`; `Retryable(IngressTechnicalFailure)` could not be injected; the old unsuitable reason required a public fault-injection API / Architecture Amendment. |
| CV-018 | `blocked (no public/controlled schedule/claim surface)`; the old record said no `schedule_work`/`claim` API existed and required a public scheduler Work API, while noting `schedule_agency_wake` was not generic Work proof. |
| CV-019 | `blocked (no public/controlled fence surface)`; the old record said no `claim`/fence injection API existed and required a public fence injection API; `terminalize_work` was correctly recorded as termination only. |
| CV-028 | `blocked (no public surface)`; the old record said no public SemanticService/rebuild/delete/query API existed and required a semantic Architecture Amendment. |
| CV-029 | `blocked (no public surface)`; the old record said no public BlobService/blob-read API existed and required a blob Architecture Amendment. |
| CV-034 | `blocked (no public/controlled cognitive-injection + Work-execution surface)`; the old record said `cognition: String` was not Decision injection and required a public Agency execution API. |
| CV-035 | `blocked (no public/controlled cognitive-injection + Work-execution surface)`; the old record said no deterministic Decision injection plus execution seam existed and required a public Agency execution API. |
| CV-036 | `blocked (no public/controlled cognitive-injection + Work-execution surface)`; the old record said `Rejected` could not be driven/observed from `schedule_agency_wake` and required a public Agency execution API. |
| CV-037 | `blocked (no public/controlled claim surface)`; the old record said no concurrent `claim`/`execute`/fence API existed and required a public scheduler claim API. |

Those records are preserved as the historical candidate's evidence, not as the
current result. The correction audit below is the effective contract against
the current baseline `95f7e7a0233cfa917d0c9656b990fd2af4996874`.

## Correction Audit — current effective candidate

The nine rows above are specified with existing test-only driver seams. On
this effective candidate, CV-017, CV-018, CV-019, CV-034, CV-035, CV-036 and
CV-037 are suitable with existing public observation surfaces, while CV-028
and CV-029 remain blocked for formal-read gaps: `CV-012..CV-040` = **27
suitable / 2 blocked**; the full `CV-001..CV-040` ledger = **38 suitable / 2
blocked**. This is a current effective count and must not be added to or
substituted for the historical 31/9 result. A future run may change the
current count only on real execution evidence, never by treating fixture setup
or internal state as a pass.

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

## Historical Candidate Matrix Overview (preserved)

The summary below is retained from the pre-policy candidate for auditability.
The current effective overlay follows it and is authoritative for the nine
corrected rows. The following Detailed Specifications section expands each row
to the full contract so Executors need not choose semantics.

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
| CV-018 | Scheduler logical head ordering on one Timeline (`world-runtime.md` §8.3-§8.4, `m5/t4`) | No public Work scheduling/claim — blocked | No public `schedule_work` or `claim` API; only `AdminService::timeline_logical_status` read exists | Blocked: no public/controlled `schedule`/`claim` surface to create or observe head ordering — explicit gap, requires public scheduler Work API per Stop Conditions | blocked (no public/controlled schedule/claim surface) | No — blocked | T12 (#317) | `m5/t4` head-aware scheduler claim; `loom-storage` `postgres_work` head ordering | No public `schedule_work`/`claim` API; `schedule_agency_wake` is scheduling only for agency wakes, not generic Work head proof — explicit gap, requires public scheduler Work API before Validator coverage |
| CV-019 | Stale fencing / ownership cannot commit after authority moved (`world-runtime.md` §8.1, `runtime-contracts.md` §14, `m5/t4`) | No public fence injection — blocked | No public `claim`/`complete` or fence token injection API; only `AdminService::terminalize_work` and `AdminService::timeline_logical_status` reads exist | Blocked: no public/controlled `lease`/`fence` injection surface to create or observe stale fencing — explicit gap, requires public scheduler fence injection API per Stop Conditions | blocked (no public/controlled fence surface) | No — blocked | T12 | `loom-storage` `postgres_work_stale_completion` stale fence; `m5/t4` claim fence | No public `claim`/`fence` injection API; `terminalize_work` is termination only, not stale claim — explicit gap, requires public fence injection API before Validator coverage |
| CV-020 | Independent Timelines not globally serialized (`world-runtime.md` §8.4, `m5/t4`) | Two Worlds/Timelines each with Pending Work at same World Time | `TimelineService::fork` (to create sibling), `ActionService::invoke` per Timeline, `HistoryService::list_events` per Timeline | Work on Timeline B commits while Timeline A head remains Pending; no cross-Timeline head barrier | controlled InMemory, controlled PostgreSQL, External | No | T12 | `m5` timeline isolation; `m6/t5` fork ancestry isolation | — |
| CV-021 | Explicit World Time advance via authority path (`world-runtime.md` §6, `m5/t5`) | Timeline quiescent (no semantically due Pending Work); current `WorldInstant` = T10 | `AdminService::advance_world_time` (`AdminAdvanceWorldTimeRequest` with `expected_version`), `TimelineService::inspect_timeline` | `AdvanceWorldTime(T10→T20)` CAS succeeds, `state_revision` increments, `world_time==T20`; replay via `inspect_timeline` at new version shows persisted time | controlled InMemory, controlled PostgreSQL | No | T13 (#318) | `m5/t5` time driver CAS; `loom-storage` timeline logical journal | — |
| CV-022 | Due Work blocks invalid time advancement (`world-runtime.md` §8.5, `m5/t5`) | Timeline has semantically due Pending Work (`effective_due <= world_time`) in backoff | `AdminService::advance_world_time`, `TimelineService::inspect_timeline` | `advance_world_time` returns rejection/Conflict with `due-work quiescence barrier` message; `inspect_timeline.world_time` remains T10; Work not skipped | controlled InMemory, controlled PostgreSQL | Yes (PostgreSQL proves barrier is logical not operational) | T13 | `m5/t5` due-work barrier; `loom-storage` work quiescence | — |
| CV-023 | Chronology reconstruction deterministic from committed history (`world-runtime.md` §9, `m6/t1-t5`) | World with committed Events + logical Time/Work transitions, then restart | `TimelineService::inspect_timeline`, `HistoryService::list_events`, `HistoryService::list_events_page` | After restart, `list_events` order and `EventSeq` equal pre-restart; `world_time` and work order reconstructed from logical journal, not `available_at` or row order | controlled InMemory, controlled PostgreSQL, controlled restart | Yes (restart recovery must be durable) | T13 | `m6/t1-t5` replay determinism; `loom-storage` `postgres_restart_resume` | — |
| CV-024 | Reaction atomicity with triggering commit (`runtime-contracts.md` §5.7, `core.md` §6, `m5/t6`) | `neutral.counter` Reaction `COUNTER_INCREMENTED_EVENT` → `COUNTER_INCREMENT_WORK` (`increment` triggers Reaction; `seed` does not) | `ActionService::invoke(ActionRequest::new(target, ActionInvocation::new(ActionTypeId::from("neutral.counter.increment"), json!({ "entity_id": entity_id.to_string(), "amount": 1 }))))` → `ExecutionResult::Committed`, `HistoryService::list_events` + `AdminService::timeline_logical_status` for `Pending` Work `effective_due_world_time` | Triggering `incremented` Event and `increment_work` schedule share same `Logical Commit` (`TimelineVersion` increments once); `list_events` shows `incremented`, `timeline_logical_status` shows `Pending` `increment_work`; no half-state | controlled InMemory, controlled PostgreSQL | No | T13 | `m5/t6` reaction atomic scheduling; `loom-runtime` reaction expansion | — |
| CV-025 | History/trajectory positive isolation - sibling state does not leak (`m6/t5`, `runtime-contracts.md` §9) | World with fork: parent → child A and sibling B; each with branch-local Event | `HistoryService::list_events`, `HistoryService::entity_trajectory`, `TimelineService::inspect_timeline` (`ancestry`), `QueryService::get_facet` | `list_events(child A)` contains ancestor + A events only, excludes B events and ancestor-future; `entity_trajectory` per Timeline respects same; `get_facet(child A, entity)` reflects `15` while `get_facet(sibling B)` reflects `5`; ordering by `EventSeq` | controlled InMemory, controlled PostgreSQL | No | T14 (#319) | `m6/t5` fork visibility; `loom-storage` `postgres_read` history parity | — |
| CV-026 | Causal/query read branch/world isolation (`m6/t5`, `m7/t1`) | Events with valid causal links (child → ancestor); invalid sibling link attempt | `HistoryService::direct_causes` / `direct_effects` / `causal_walk`, `HistoryService::get_event` | Valid ancestor causal link query succeeds; sibling/unrelated World/ancestor-future causal reference rejected at commit and not returned by `causal_walk`; ordering uses `EventSeq` | controlled InMemory, controlled PostgreSQL | No | T14 | `m6/t5` causality isolation; `m7/t1` history/trajectory reads | — |
| CV-027 | World-scoped Catalog requires Binding + active Revision (`world-runtime.md` §3/§4, `m4/t2`, `m7/t1`) | World with Binding `{counter}` under R-comp; second check with no active revision (test fixture) | `CatalogService::catalog`, `CatalogService::catalog_for_world` | With active compatible revision, `catalog_for_world == {counter}` visible; with no active revision, `catalog_for_world` returns unavailable/empty does not use global registry; sibling World with different Binding shows different catalog | controlled InMemory, controlled PostgreSQL | No | T14 | `m4/t2` binding-aware catalog; `m7/t1` binding-aware catalog; `runtime_authority` CV-010/011 negative checks | — |
| CV-028 | Semantic projection rebuildable, not authority (`m7/t2-t3`) | Capability-owned semantic index built from committed Events; then deleted | No public SemanticService exists; authority only via `HistoryService::list_events` + `QueryService::get_facet` + `CatalogService::catalog` | Blocked: no public API to create/rebuild/delete/query semantic projection; Validator cannot observe semantic projection via public surface — gap requires new authority | blocked (no public surface) | No | T15 (#320) | `m7/t2` pgvector projection rebuild; `m7/t3` retrieval not authority | No public SemanticService/rebuild API; current `loom-api`/`loom-client` lack semantic projection public surface — explicit gap, requires Architecture Amendment before Validator coverage |
| CV-029 | Blob/reference availability failure does not rewrite history (`m7/t4`) | Facet with Blob reference; BlobStore explicitly missing | No public BlobService exists; authority only via `QueryService::get_facet` (Facet contains `BlobReference` value) + `HistoryService::list_events` | Blocked: no public blob read API; Validator can only observe Facet value via `get_facet`, cannot validate blob fetch failure via public surface — gap requires new authority | blocked (no public surface) | No | T15 | `m7/t4` immutable BlobStore; `m7/t4` missing blob not history rewrite | No public BlobService/blob read API; blob availability cannot be validated via current public `loom-api` — explicit gap, requires Architecture Amendment |
| CV-030 | Pinned/versioned read via fork at version (`m7/t5`, `amendment 0003 §4`) | World at `TimelineVersion { head_event_seq: 10, state_revision: 100 }` value `counter=10`; then second commit `counter=11` at `head_event_seq: 11` | `TimelineService::fork(ForkTimelineRequest::at_version(source, TimelineVersion{10,100}))` then `QueryService::get_facet(FacetQuery::new(fork_target, owner, facet_type))` + `TimelineService::inspect_timeline` | Fork target `get_facet` returns `10` (value at pinned version) even though head `get_facet` returns `11`; fork `inspect_timeline.ancestry` preserves `fork_parent_version` | controlled InMemory, controlled PostgreSQL | Yes (pinned consistency must be persistent) | T15 | `m7/t5` scalable pinned reads via fork-at-version; amendment 0003 | — (implementable via existing `ForkTimelineRequest::at_version` + `get_facet`; no `get_facet_at_version`/`BaseWorldView` invented) |
| CV-031 | Event→Session→Revision provenance retained after revision change (`m9/t2-t3`, `evolution.md`) | Session S1 under R1 commits Event E1 | `HistoryService::list_events`/`get_event` for history, `AdminService::session_for_event(EventRef)` + `AdminService::get_execution_session(AdminExecutionSessionRequest)` for provenance | `AdminService::session_for_event(E1) -> S1` and `get_execution_session(S1).runtime_revision_id == R1` even after R2 activation; `list_events` shows `CommittedEvent` history only | controlled InMemory, controlled PostgreSQL, controlled restart | Yes | T16 (#321) | `m9/t2` Session provenance; `m9/t3` Event→Session atomic linkage | — |
| CV-032 | New Session after compatible R2 uses R2 without rewriting history (`m9/t1`, `m9/t5`) | After R2 activation, new Action via new Session S2 | `ActionService::invoke`, `TimelineService::inspect_timeline`, `AdminService::session_for_event` + `get_execution_session` | `get_execution_session(S2).runtime_revision_id == R2` and `session_for_event(E2) == S2`; `list_events` history reread of E1 still via `get_event` shows `CommittedEvent` unchanged, provenance via `session_for_event(E1) == S1` | controlled InMemory, controlled PostgreSQL | Yes | T16 | `m9/t5` R1/R2 session switch; `loom-storage` `postgres_revision` activation | — |
| CV-033 | Implementation/call/entropy provenance tied to committed execution (`m9/t2`) | Session S1 with `read_set`, `call_provenance`, `entropy_evidence` via `get_execution_session` | `AdminService::get_execution_session(AdminExecutionSessionRequest { session_id }) -> AdminExecutionSession { runtime_revision_id: String, read_set: Vec<AdminReadDependency>, call_provenance: Vec<AdminResolutionCallEdge>, entropy_evidence: AdminEntropyEvidence }` + `AdminService::get_runtime_revision(AdminRuntimeRevisionRequest { revision_id }) -> AdminRuntimeRevision { capabilities: Vec<AdminRuntimeRevisionCapability { implementation_id, version }> }` for version | `get_execution_session(S1).runtime_revision_id == R1` via `get_runtime_revision(R1).capabilities[0].version == "1.7.3"`; `read_set: Vec<AdminReadDependency::Facet { owner: FacetOwner, facet_type: FacetTypeId, schema_revision: Option<SchemaRevision> }>`/`call_provenance`/`entropy_evidence` remain stable | controlled InMemory, controlled PostgreSQL | Yes | T16 | `m9/t2` provenance evidence round-trip; `m9/t3` linkage survival after restart — internal, not public Validator evidence. | `read_set` etc do not carry version; version via `runtime_revision_id` + `get_runtime_revision` |
| CV-034 | Agency NoAction completes wake without fabricating Event (`m10/t4`, `amendment 0003 §3.5`) | No cognitive injection seam — blocked | `cognition: String` is requirement, `AdminService::schedule_agency_wake` only creates `Pending` Work; no controlled `Decision` injection/`execute_work` seam | Blocked: no public/controlled `with_cognitive_executor` + `execute_work` surface; `schedule_agency_wake` only creates `Pending` | blocked (no public/controlled Agency execution surface) | No — blocked | T17 (#322) | `m10/t4` NoAction atomic; `loom-agency` contracts. | `cognition: String` is requirement not `Decision` provider; `schedule_agency_wake` only creates `Pending` Work — explicit gap, requires public Agency execution API before Validator coverage |
| CV-035 | Agency Act enters normal Action authority path (`m10/t4`) | No cognitive injection seam — blocked | No public `Decision` injection; `cognition` String is requirement | Blocked: no public/controlled `with_cognitive_executor` + `execute_work` surface; `schedule_agency_wake` only creates `Pending` | blocked (no public/controlled Agency execution surface) | No — blocked | T17 | `m10/t4` Act via normal path; `m10` Agency gate | No public `Decision` injection — explicit gap, requires public Agency execution API |
| CV-036 | Agency semantic rejection produces no false Event (`m10/t4` R-1) | No cognitive injection seam — blocked | No public `Decision` injection | Blocked: no public/controlled cognitive-injection + `execute_work` surface; `ExecutionResult::Rejected` cannot be observed via `schedule_agency_wake` alone | blocked (no public/controlled Agency execution surface) | No — blocked | T17 | `m10/t4` R-1 rejected wake completes; `m10/t5` no stale retry | No public `Rejected` observation via `schedule_agency_wake` alone — explicit gap, requires public Agency execution API |
| CV-037 | Concurrent CAS loser cannot overwrite winner, provenance records path (`m10/t5`) | No public claim API — blocked | No public claim/execute surface; only `AdminService::schedule_agency_wake` (scheduling) + `AdminService::timeline_logical_status` read exists | Blocked: no public/controlled `claim`/`execute`/`fence` surface to create or observe concurrent CAS — explicit gap, requires public scheduler claim API per Stop Conditions | blocked (no public/controlled claim surface) | No — blocked | T17 | `m10/t5` CAS resample vs reuse; `loom-storage` `postgres_work_stale_completion` | No public concurrent claim/execute API; `schedule_agency_wake` is scheduling only — explicit gap, requires public scheduler claim API before Validator coverage |
| CV-038 | Committed Event observable via formal change-feed/SSE client (`m8/t4-t6`) | Timeline with committed Event; formal client `SubscriptionRequest::new` | `SubscriptionService::subscribe` / `poll_change_feed`, `HistoryService::list_events` correlation | `ChangeFeedPage`/`SubscriptionResult::Events` contains committed `EventId` with same `EventSeq`/payload as `list_events`; cursor `next_cursor` monotonic | External (real HTTP/SSE), controlled InMemory, controlled PostgreSQL | No | T18 (#323) | `m8/t4` change feed; `m8/t5` HTTP/SSE boundary | — |
| CV-039 | Resume from valid cursor continues at documented boundary (`m8/t4`) | Change feed cursor at `EventSeq=5` (`ChangeFeedCursor::after(target, EventSeq(5))`); new events `6,7` committed after | `SubscriptionService::subscribe(SubscriptionRequest::resume(target, ChangeFeedCursor::after(target, EventSeq(5)), limit))` → `SubscriptionResult::Events(ChangeFeedPage { events: [E6,E7], next_cursor: Some(ChangeFeedCursor::after(target, EventSeq(7))) })` and `ChangeFeedPage.next_cursor: Option<ChangeFeedCursor>` for resume | First resume returns `Events` with `E6,E7`; second resume with no new events returns `Resumed(SubscriptionResume { cursor: ChangeFeedCursor::after(target, EventSeq(7)) })` | controlled InMemory, controlled PostgreSQL | Yes (cursor durability across restart) | T18 | `m8/t4` resume semantics; `loom-storage` change feed page/cursor | — |
| CV-040 | Disconnect/reconnect recovery preserves history, transport duplicate != world duplicate (`m8/t5-t6`) | Formal client disconnect mid-page; reconnect with same cursor | `SubscriptionService::subscribe(SubscriptionRequest::new(target, limit))` → disconnect → `SubscriptionService::subscribe(SubscriptionRequest::resume(target, cursor, limit))`, `HistoryService::list_events` + `ChangeFeedPage.next_cursor: Option<ChangeFeedCursor>` | History `list_events` still exactly N authoritative commits; transport retry may deliver page again but `EventId` dedup shows no second commit; `SubscriptionResult::Events(ChangeFeedPage)` vs `Backpressure`/`Reconnect` distinguishable | controlled InMemory, controlled PostgreSQL, controlled restart | Yes (reconnect recovery durable) | T18 | `m8/t6` http-client reconnect; `m8/t8` black-box gate | — |

## Current Effective Matrix Overview — correction overlay

The nine rows below explicitly separate the **test-only driver**, **public
observable evidence**, and **product API / architecture-gap** decision. The
driver is never evidence; the public surface is the only basis for a result.

| CV | Test-only driver (setup/control only) | Public observable evidence | Product API / architecture-gap rule | Current expected result | Evidence / PG | Owner |
| --- | --- | --- | --- | --- | --- | --- |
| CV-017 | Controlled `Runtime` + `Ingress` + `Storage`/restart fixture injects `Retryable(IngressTechnicalFailure)`, recovery, and duplicate submission boundary. | `LoomClient` `IngressService::ingress_status` plus `HistoryService`/`QueryService`. | Existing `IngressService` is sufficient; missing production fault-injection API is not a gap. Block only if Runtime retry authority/semantic or these reads are absent. | Retryable status produces no Event; recovery produces exactly one authoritative Event/Facet; duplicate submission does not add another. | controlled InMemory, controlled PostgreSQL; PG restart if durability is asserted. | T11 (#316) |
| CV-018 | Controlled `Scheduler` + `WorkStore` + `Runtime` fixture creates two same-Timeline ordered Pending Works and claim conditions. | `LoomClient` `AdminService::timeline_logical_status` Work/journal fields plus `HistoryService` ordering. | Generic production `schedule_work`/`claim` is not required when the controlled fixture drives existing authority. Block only if Work ordering/head authority or formal reads are absent. | Logical head admits the earliest `(effective_due_world_time, logical_schedule_order)` Work and preserves order; later Work does not bypass it. | controlled InMemory, controlled PostgreSQL; PG when durable Work state is asserted. | T12 (#317) |
| CV-019 | Controlled `Scheduler` + `WorkStore` fixture creates stale/new fence or lease competitors and completion attempts. | `LoomClient` `AdminService::timeline_logical_status`, completion/history, and provenance reads. | `terminalize_work` is not a claim driver; no production claim API is required for this test-only seam. Block only if Runtime fence authority/semantic or formal reads are absent. | Stale actor is rejected; winner remains authoritative and cannot be overwritten. | controlled InMemory, controlled PostgreSQL; PG for durable fencing if required. | T12 (#317) |
| CV-028 | Test-only Runtime-owned projection/storage fixture may build, delete, and rebuild a derived semantic projection from committed Events; driver is setup only. | Only `LoomClient` `HistoryService::list_events` and `QueryService::get_facet` are existing formal reads; `SemanticIndexDescriptor` is catalog metadata only. | **Blocked — `no existing formal semantic projection observable`**: no formal SemanticProjection read/rebuild/delete surface exists. This is a formal-read gap, not a product-API amendment request. | `Unavailable` until a formal semantic projection observable exists; internal projection state cannot establish Pass. | **No — blocked** (`no existing formal semantic projection observable`); PG not applicable while blocked. | T15 (#320) |
| CV-029 | Test-only Runtime-owned projection/blob/storage fixture may create a Facet `BlobReference` and clear the referenced blob; BlobStore is setup only. | Only `LoomClient` `QueryService::get_facet` and `HistoryService::list_events` are existing formal reads; `FacetSnapshot.value` is opaque `Value`. | **Blocked — `no existing formal blob/reference fetch observable`**: no formal blob fetch/read surface exists. This is a formal-read gap, not a product-API amendment request. | `Unavailable` until a formal blob/reference fetch observable exists; internal BlobStore/SQL cannot establish Pass. | **No — blocked** (`no existing formal blob/reference fetch observable`); PG not applicable while blocked. | T15 (#320) |
| CV-034 | Agency/Runtime controlled fixture installs deterministic `CognitiveExecutor` returning `Decision::NoAction` for a scheduled Wake and drives the Work boundary. | `LoomClient` `AdminService::timeline_logical_status`, `HistoryService`, `QueryService`, and session/provenance read. | `cognition: String` remains a request field; the controlled executor is a test driver, not a new product API. Block only if the existing Wake/NoAction authority or formal reads are absent. | Pending Wake becomes terminal/Completed with no fabricated Event or Facet mutation. | controlled InMemory, controlled PostgreSQL as applicable; PG not mandatory by policy. | T17 (#322) |
| CV-035 | Agency/Runtime controlled fixture installs deterministic `CognitiveExecutor` returning legal `Decision::Act` and drives the scheduled Wake. | `LoomClient` logical status, `HistoryService`, `QueryService`, and session/provenance read. | Normal Action authority is reused; no public Decision-injection API is required. Block only if Agency Act authority/semantic or formal reads are absent. | Wake reaches terminal committed state through normal Action authority; expected Event/Facet and provenance are visible. | controlled InMemory, controlled PostgreSQL as applicable; PG not mandatory by policy. | T17 (#322) |
| CV-036 | Agency/Runtime controlled fixture installs deterministic `CognitiveExecutor` returning a semantically invalid Act and drives the Wake. | `LoomClient` logical status, `HistoryService`, `QueryService`, and session/provenance read. | Rejection is existing Action/semantic authority; no public rejection-injection API is required. Block only if rejection semantics or formal reads are absent. | Wake reaches terminal Rejected/no-world-change state; no fabricated Event, Facet mutation, or false completion is observed. | controlled InMemory, controlled PostgreSQL as applicable; PG not mandatory by policy. | T17 (#322) |
| CV-037 | Agency/Runtime controlled fixture creates two stale/new CAS or fence competitors for one logical-head Wake and records deterministic winner/loser Decisions. | `LoomClient` logical status, `HistoryService`, `QueryService`, and session/provenance reads. | Test-only claim/fence control is allowed; no production claim API is required. Block only if Runtime CAS/fence authority or formal winner/loser/provenance reads are absent. | One winner remains authoritative; stale loser is rejected/discarded; no overwrite or fabricated Event; provenance distinguishes winner/loser path. | controlled InMemory, controlled PostgreSQL as applicable; PG not mandatory by policy. | T17 (#322) |

## Detailed Scenario Specifications

Each scenario below expands the required matrix columns so T10–T18
Executors can implement without semantic choice. The nine corrected rows
(`CV-017`, `CV-018`, `CV-019`, `CV-028`, `CV-029`, `CV-034`, `CV-035`,
`CV-036`, `CV-037`) use explicit test-only drivers and public observable
evidence below. The old 9-blocked wording is preserved in the historical
record; it is not the current effective status. Future discovery of a missing
Runtime authority/semantic, driver, or formal read must mark only the affected
row blocked and stop.

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
- **Formal Surface:** `ActionService::invoke(ActionRequest::new(target, ActionInvocation::new(ActionTypeId::from("neutral.counter.seed"), json!({ "event_id": event_id.to_string(), "entity_id": entity_id.to_string(), "value": 1 }))))`, `QueryService::get_facet(FacetQuery::new(target, FacetOwner::entity(entity_id), FacetTypeId::from("neutral.counter.value")))`, `HistoryService::list_events(EventQuery::all(target))`.
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

### CV-017 — Ingress operational bookkeeping distinct from authoritative history (current effective contract)

- **Stable CV ID:** `CV-017`
- **Clause:** `world-runtime.md` §2.2 vs §2.5 vs §2.6; `m8/t2` Ingress platform lifecycle; `loom-api::IngressStatus`.
- **Test-only Driver:** Controlled `Runtime` + `Ingress` + `Storage`/restart fixture injects `Retryable(IngressTechnicalFailure)` after acceptance, drives recovery, and repeats the submission at the duplicate boundary. This is setup/control only, not evidence.
- **Public Observable Evidence:** `LoomClient` `IngressService::ingress_status(IngressId)` observes `Retryable` and terminal completion; `HistoryService::list_events` and `QueryService::get_facet` observe authoritative Event/Facet state. No SQL or internal storage read is an assertion.
- **Product API / Architecture Gap:** Existing Runtime/Ingress authority and formal reads are sufficient. The absence of a production fault-injection endpoint is not a gap. Mark `blocked` only if the Runtime retry authority/semantic, controlled driver, or formal observations are genuinely absent.
- **Expected Result:** `Retryable(IngressTechnicalFailure)` creates no Event or Facet mutation. Recovery reaches `Completed(IngressCompletion::Committed { event_refs, timeline_version })` with exactly one authoritative Event/Facet; repeating the same submission does not add a second EventRef. `Retryable` is never rendered as `Completed(Rejected)`.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL; controlled restart when durable recovery is asserted.
- **PostgreSQL Live Mandatory:** No — PG evidence remains available for durability, but the logical Retryable/no-Event boundary is not itself PG-mandatory.
- **Owner:** T11
- **Complementary:** `m8/t2` status vs history table separation; `m8/t3` recovery not inventing truth — internal, not public Validator evidence.
- **Unsuitable Reason:** — (suitable when the existing controlled driver and public observations execute; missing production injection API alone is not an unsuitable reason).

### CV-018 — Single-Timeline logical head ordering (current effective contract)

- **Stable CV ID:** `CV-018`
- **Clause:** `world-runtime.md` §8.3-§8.4 Deterministic logical Work order, Head-of-line rule; `runtime-contracts.md` §14; `m5/t4` head-aware scheduler claim.
- **Test-only Driver:** Controlled `Scheduler` + `WorkStore` + `Runtime` fixture creates two same-Timeline ordered Pending Works at `T20`, establishes claim conditions, and advances the controlled Work boundary. This is setup/control only, not evidence.
- **Public Observable Evidence:** `LoomClient` `AdminService::timeline_logical_status` reads Work and logical-journal state; `HistoryService` observes the resulting admission/order. The test does not use SQL or internal Work state as an assertion.
- **Product API / Architecture Gap:** Existing Scheduler/Work authority is exercised through the controlled fixture. Missing production `schedule_work`/`claim` endpoints is not a gap. Mark `blocked` only if logical-head authority/semantic or these formal reads are absent.
- **Expected Result:** The logical head admits the earliest `(effective_due_world_time, logical_schedule_order)` Work; the later Work cannot bypass it. The formal logical status and resulting history show deterministic head/order.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL; PG when durable Work state is part of the claim.
- **PostgreSQL Live Mandatory:** No — PG is optional for this logical ordering row unless the implementation claims durable Work ordering.
- **Owner:** T12 (#317)
- **Complementary:** `m5/t4` claim with `SKIP LOCKED` head-only; `loom-storage/tests/postgres_work.rs` ordering — internal, not public Validator evidence.
- **Unsuitable Reason:** — (suitable when the existing controlled driver and public observations execute; missing production scheduling/claim API alone is not an unsuitable reason).

### CV-019 — Stale fencing / ownership cannot commit after authority moved (current effective contract)

- **Stable CV ID:** `CV-019`
- **Clause:** `world-runtime.md` §8.1 Semantic due vs operational claimability; `runtime-contracts.md` §14 claim/admission; `implementation.md` §13.3 `SKIP LOCKED` scope; `m5/t4`.
- **Test-only Driver:** Controlled `Scheduler` + `WorkStore` fixture creates stale/new lease or fence competitors, performs the authoritative claim/complete attempts, and supplies the stale actor boundary. `AdminService::terminalize_work` is not used as a claim driver.
- **Public Observable Evidence:** `LoomClient` `AdminService::timeline_logical_status` observes Work ownership/status; completion/history and session/provenance reads observe the winner and its authority. Internal fence values and SQL are not assertions.
- **Product API / Architecture Gap:** Existing Runtime fence authority and controlled seam are sufficient. Missing public claim/fence injection is not a gap. Mark `blocked` only if fence/lease authority/semantic or the formal observations are genuinely absent.
- **Expected Result:** The stale actor is rejected and cannot complete/overwrite the Work. The winner's authoritative state remains unchanged by the stale attempt, and the formal history/provenance read identifies the winning path.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL; controlled restart if durable fencing is asserted.
- **PostgreSQL Live Mandatory:** No — PG is optional for the logical stale-fence boundary unless durable lease/fence persistence is claimed.
- **Owner:** T12
- **Complementary:** `loom-storage/tests/postgres_work_stale_completion.rs`; `m5/t4` fence.
- **Unsuitable Reason:** — (suitable when the controlled claim/fence driver and public observations execute; `terminalize_work` remains termination-only).

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
- **Preconditions:** Capability `neutral.counter` with `Reaction` registered for `EventType "neutral.counter.incremented"` → `neutral.counter.increment_work` (existing fixture `neutral.counter` Reaction `COUNTER_INCREMENTED_EVENT` → `COUNTER_INCREMENT_WORK` `loom-neutral/src/lib.rs:259-262`); `EntityId` seeded via `neutral.counter.seed` (`value: 5`, `entity_id` fresh) before `increment` trigger.
- **Formal Surface:** `ActionService::invoke(ActionRequest::new(target, ActionInvocation::new(ActionTypeId::from("neutral.counter.increment"), json!({ "entity_id": entity_id.to_string(), "amount": 1 })))) -> ExecutionResult::Committed { event_ids: Vec<EventId>, timeline_version: TimelineVersion }` (requires `neutral.counter.seed` with `value: 5` to have created `entity_id` first; `increment`'s `COUNTER_INCREMENTED_EVENT` (`EventTypeId("neutral.counter.incremented")`) triggers registered `Reaction` `neutral.counter.increment_work`), `HistoryService::list_events(EventQuery::all(target)) -> Vec<CommittedEvent>` + `HistoryService::list_events_page(EventQuery::all(target)) -> EventPage { events: Vec<CommittedEvent>, next_after: Option<EventSeq> }` for `EventSeq` order, `TimelineService::inspect_timeline(TimelineTarget) -> TimelineSnapshot { version, world_time }` for `version`, `AdminService::timeline_logical_status(TimelineTarget) -> AdminTimelineLogicalStatus { works: Vec<AdminLogicalWorkStatus>, version, chronology_budget }` for reaction `Pending` Work `effective_due_world_time`/`logical_schedule_order` observation.
- **Expected Result:** Triggering `CommittedEvent { event_type: EventTypeId("neutral.counter.incremented") }` (`neutral.counter.increment` on seeded `entity_id`) and `Reaction` `neutral.counter.increment_work` schedule share same `Logical Commit` (`TimelineVersion` increments once for `increment`); `HistoryService::list_events(EventQuery::all(target))` shows `incremented` Event (`COUNTER_INCREMENTED_EVENT`), `AdminService::timeline_logical_status(TimelineTarget) -> AdminTimelineLogicalStatus { works }` shows `Pending` Work `neutral.counter.increment_work` with `effective_due_world_time == trigger Commit occurred_at`; no half-state where `incremented` Event durable but `increment_work` `Pending` lost across `BackendContext::restart()`. Second `Runtime::execute_work(target, work_id, now, claimed_until, retry_available_at)` `Logical Commit` produces separate `CommittedEvent { event_type: "neutral.counter.incremented" }` via `increment_work`; `BackendContext::restart()` preserves both via `timeline_logical_status`.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL.
- **PostgreSQL Live Mandatory:** No (atomicity logical; PostgreSQL validates durability).
- **Owner:** T13
- **Complementary:** `m5/t6` reaction atomic scheduling; `loom-runtime` reaction.
- **Unsuitable Reason:** —

### CV-025 — History/trajectory positive isolation - sibling leak excluded

- **Stable CV ID:** `CV-025`
- **Capability / Clause:** `m6/t5` History visibility after fork; `runtime-contracts.md` §9.1; `world-runtime.md` §3.
- **Preconditions:** World fork as in CV-007: parent seeded `value=5`, child fork A incremented to `15`, sibling B untouched. Entity fresh.
- **Formal Surface:** `HistoryService::list_events(EventQuery::all(target))`, `HistoryService::entity_trajectory(EntityTrajectoryQuery::all(target, entity_id))`, `TimelineService::inspect_timeline` for `ancestry`, `QueryService::get_facet(FacetQuery::new(target, owner, facet_type))` for facet isolation check.
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

### CV-028 — Semantic projection rebuildable, not authority (current effective contract — blocked formal-read gap)

- **Stable CV ID:** `CV-028`
- **Clause:** `m7/t2` semantic indexes + pgvector, `m7/t3` mediator, `implementation.md` placeholder for vector.
- **Test-only Driver:** A controlled `Runtime::new` over `InMemoryStore` or `PgStorage` may use the Runtime-owned `SemanticProjectionStore` seam to commit representative Events, call `Runtime::rebuild_semantic_projection`, remove materialization with `SemanticProjectionStore::delete_semantic_projection`, and rebuild from authoritative history. This is setup/control only and cannot be Pass evidence.
- **Public Observable Evidence:** The only existing formal reads are `LoomClient` `HistoryService::list_events` and `QueryService::get_facet`, which observe authoritative Events/Facets. `SemanticIndexDescriptor` through catalog is metadata only; there is no formal SemanticProjection read/rebuild/delete surface. Internal projection state, BlobStore, and SQL are not evidence.
- **Product API / Architecture Gap:** **Blocked — `no existing formal semantic projection observable`.** The current Runtime projection contract cannot be certified for derived rebuildability through the available `LoomClient` reads. This records the formal-read gap only; it does not request or require an Architecture Amendment or product API.
- **Expected Result:** `Unavailable` for the derived projection assertion: the driver may remove/rebuild it, but no existing formal observable can prove that operation. `HistoryService::list_events` and `QueryService::get_facet` remain the only authoritative reads and cannot be promoted to projection evidence.
- **Evidence Classes:** **blocked (no existing formal semantic projection observable)**; no External, controlled InMemory, or controlled PostgreSQL Pass evidence applies while blocked.
- **PostgreSQL Live Mandatory:** No — blocked on the formal-read gap; PG cannot substitute for a missing public observable.
- **Owner:** T15 (#320)
- **Complementary:** `m7/t2` pgvector add/rebuild leaves authority unchanged; `m7/t3` read not authority — internal evidence, not public Validator evidence.
- **Unsuitable Reason:** **Blocked — `no existing formal semantic projection observable`**; the test-only driver and internal projection state cannot establish Validator acceptance.

### CV-029 — Blob/reference missing does not rewrite history (current effective contract — blocked formal-read gap)

- **Stable CV ID:** `CV-029`
- **Clause:** `m7/t4` immutable BlobStore; `implementation.md` blob.
- **Test-only Driver:** A controlled `Runtime::new` over `InMemoryStore` or `PgStorage` with `InMemoryBlobStore` may commit a Facet containing a `BlobReference`, then remove or make that reference unavailable without changing the authoritative record. BlobStore/SQL is setup only and cannot be acceptance evidence.
- **Public Observable Evidence:** The only existing formal reads are `LoomClient` `QueryService::get_facet` and `HistoryService::list_events`; `FacetSnapshot.value` is opaque `Value`. No formal blob fetch/read surface exists to observe `Unavailable`/missing reference.
- **Product API / Architecture Gap:** **Blocked — `no existing formal blob/reference fetch observable`.** This records the missing formal observable only; it does not request or require an Architecture Amendment or product API.
- **Expected Result:** `Unavailable` for the missing-blob assertion: the driver may make the reference unavailable, but no existing formal observable can prove the failed fetch. `get_facet` and `list_events` remain authoritative and must not be replaced by internal BlobStore/SQL evidence.
- **Evidence Classes:** **blocked (no existing formal blob/reference fetch observable)**; no External, controlled InMemory, or controlled PostgreSQL Pass evidence applies while blocked.
- **PostgreSQL Live Mandatory:** No — blocked on the formal-read gap; PG cannot substitute for a missing blob/reference observable.
- **Owner:** T15
- **Complementary:** `m7/t4` blob immutability; `loom-storage` blob tests — internal, not public Validator evidence.
- **Unsuitable Reason:** **Blocked — `no existing formal blob/reference fetch observable`**; internal BlobStore/SQL setup cannot establish Validator acceptance.

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
- **Formal Surface:** `AdminService::get_execution_session(AdminExecutionSessionRequest { session_id }) -> AdminExecutionSession { runtime_revision_id: String, read_set: Vec<AdminReadDependency>, call_provenance: Vec<AdminResolutionCallEdge>, entropy_evidence: AdminEntropyEvidence }` (plus `cognitive_evidence: AdminCognitiveEvidence` for agency wakes) + `AdminService::get_runtime_revision(AdminRuntimeRevisionRequest { revision_id: String }) -> AdminRuntimeRevision { revision_id, capabilities: Vec<AdminRuntimeRevisionCapability { implementation_id: String, version: String }> }` for version check; `AdminReadDependency::Facet { owner: FacetOwner, facet_type: FacetTypeId, schema_revision: Option<SchemaRevision> }` shape.
- **Expected Result:** After new registry, `get_execution_session(S1).runtime_revision_id == "R1"` and `get_runtime_revision(AdminRuntimeRevisionRequest { revision_id: R1 }).capabilities[0].version == "1.7.3"` remain at commit time, not `1.8.0`; `get_execution_session(S1).read_set` (`Vec<AdminReadDependency::Facet { owner: FacetOwner, facet_type: FacetTypeId, schema_revision: Option<SchemaRevision> }>`), `call_provenance` and `entropy_evidence` remain stable and not resampled on replay; `CommittedEvent` history via `HistoryService::list_events` does not contain revision (revision only via Admin provenance).
- **Evidence Classes:** controlled PostgreSQL (durable), controlled InMemory (logical).
- **PostgreSQL Live Mandatory:** Yes (controlled PostgreSQL persistence for durable provenance via `get_execution_session` + `get_runtime_revision`)
- **Owner:** T16
- **Complementary:** `m9/t2` provenance evidence; `loom-runtime` entropy.
- **Unsuitable Reason:** —

### CV-034 — Agency NoAction completes wake without fabricating Event (current effective contract)

- **Stable CV ID:** `CV-034`
- **Clause:** `m10/t4` Atomic Agency Wake Decision/Action commit, NoAction path; `amendment 0003 §3`.
- **Test-only Driver:** `Runtime::new(...).with_cognitive_executor(DeterministicCognitiveExecutor::new([DeterministicCognitiveStep::no_action()]))`, `AdminService::schedule_agency_wake`, and `Runtime::execute_work` drive one scheduled Wake. The executor and Work control are setup only, not evidence.
- **Public Observable Evidence:** `LoomClient` `AdminService::timeline_logical_status`, `HistoryService`, `QueryService`, and session/provenance reads observe the terminal Work and unchanged world state. No internal state or SQL is an assertion.
- **Product API / Architecture Gap:** `cognition: String` remains a request requirement; deterministic executor injection is a test-only seam. Missing production Decision injection/execution API is not a gap. Mark `blocked` only if the existing Wake/NoAction authority/semantic or formal reads are absent.
- **Expected Result:** The scheduled Pending Wake becomes terminal/Completed with no fabricated Event or Facet mutation.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL as applicable.
- **PostgreSQL Live Mandatory:** No — PG is optional for this logical NoAction boundary.
- **Owner:** T17 (#322)
- **Complementary:** `m10/t4` NoAction atomic; `loom-agency` contracts — internal, not public Validator evidence.
- **Unsuitable Reason:** — (suitable when the controlled deterministic executor and formal observations execute).

### CV-035 — Agency Act enters normal Action authority path (current effective contract)

- **Stable CV ID:** `CV-035`
- **Clause:** `m10/t4` Act via normal path; `runtime-contracts.md` §8 Agency Decision.
- **Test-only Driver:** `Runtime::new(...).with_cognitive_executor(DeterministicCognitiveExecutor::new([DeterministicCognitiveStep::act(ActionInvocation::new("neutral.counter.increment", ...))]))`, `AdminService::schedule_agency_wake`, and `Runtime::execute_work` drive the Wake through the existing Action authority.
- **Public Observable Evidence:** `LoomClient` logical status, `HistoryService`, `QueryService`, and session/provenance reads observe terminal Work, committed Event/Facet, and provenance. Internal executor output is not acceptance evidence.
- **Product API / Architecture Gap:** Normal Action authority is reused; no public Decision-injection API is required. Mark `blocked` only if Agency Act authority/semantic or the formal reads are absent.
- **Expected Result:** Wake reaches terminal committed state through normal Action authority; the expected Event/Facet and session/provenance are visible.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL as applicable.
- **PostgreSQL Live Mandatory:** No — PG is optional for this logical Act boundary.
- **Owner:** T17
- **Complementary:** `m10/t4` Act via normal path — internal, not public Validator evidence.
- **Unsuitable Reason:** — (suitable when the controlled deterministic executor and formal observations execute).

### CV-036 — Agency semantic rejection produces no false Event (current effective contract)

- **Stable CV ID:** `CV-036`
- **Clause:** `m10/t4` R-1 semantic Rejected MUST complete Wake as determined no-world-change; `runtime-contracts.md` §5.4 Rejected.
- **Test-only Driver:** `Runtime::new(...).with_cognitive_executor(DeterministicCognitiveExecutor::new([DeterministicCognitiveStep::act(ActionInvocation::new("neutral.counter.increment", invalid_payload))]))`, `AdminService::schedule_agency_wake`, and `Runtime::execute_work` drive the Wake through semantic validation.
- **Public Observable Evidence:** `LoomClient` logical status, `HistoryService`, `QueryService`, and session/provenance reads observe Rejected/terminal state and no authority mutation. Internal rejection state and SQL are not assertions.
- **Product API / Architecture Gap:** Rejection is existing Action/semantic authority; no public rejection-injection API is required. Mark `blocked` only if rejection semantics or formal reads are absent.
- **Expected Result:** Wake reaches terminal Rejected/no-world-change state; no fabricated Event, Facet mutation, or false completion is observed.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL as applicable.
- **PostgreSQL Live Mandatory:** No — PG is optional for this logical rejection boundary.
- **Owner:** T17
- **Complementary:** `m10/t4` R-1; `loom-runtime` rejected path — internal, not public Validator evidence.
- **Unsuitable Reason:** — (suitable when the controlled deterministic executor and formal observations execute).

### CV-037 — Concurrent/stale CAS loser cannot overwrite winner; provenance records path (current effective contract)

- **Stable CV ID:** `CV-037`
- **Clause:** `m10/t5` Agency Wake scheduling CAS policy, resample vs reuse; `world-runtime.md` §8.1; `runtime-contracts.md` §7.3.
- **Test-only Driver:** Two controlled `Runtime::execute_work` calls over the same `WorkStore`/logical-head Wake use stale/new `TimelineVersion` or fence inputs and deterministic `CognitiveExecutor` Decisions to exercise the CAS winner/loser boundary. This is setup/control only.
- **Public Observable Evidence:** `LoomClient` `AdminService::timeline_logical_status`, `HistoryService`, `QueryService`, and session/provenance reads observe one winner, the rejected/discarded loser, and the authority/provenance outcome. No SQL or internal claim state is an assertion.
- **Product API / Architecture Gap:** Test-only claim/fence control is allowed; no production claim API is required. Mark `blocked` only if Runtime CAS/fence authority/semantic or formal winner/loser/provenance reads are absent.
- **Expected Result:** Exactly one winner remains authoritative; stale loser is rejected/discarded; no overwrite or fabricated Event occurs; provenance distinguishes winner and loser paths.
- **Evidence Classes:** controlled InMemory, controlled PostgreSQL as applicable.
- **PostgreSQL Live Mandatory:** No — PG is optional for this logical CAS boundary unless durable contention is claimed.
- **Owner:** T17
- **Complementary:** `m10/t5` stale CAS; `loom-storage/tests/postgres_work_stale_completion.rs` — internal, not public Validator evidence.
- **Unsuitable Reason:** — (suitable when the controlled CAS/fence driver and formal observations execute).

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
- **Expected Result:** First `SubscriptionRequest::resume(target, ChangeFeedCursor::after(target, EventSeq(5)), limit) -> SubscriptionResult::Events(ChangeFeedPage { events: [E6,E7], next_cursor: Some(ChangeFeedCursor::after(target, EventSeq(7))), has_more })` returns `E6,E7` only, no `E5`; `next_cursor` advances to `7`. Second `SubscriptionRequest::resume(target, ChangeFeedCursor::after(target, EventSeq(7)), limit)` with no new events returns `SubscriptionResult::Resumed(SubscriptionResume { cursor: ChangeFeedCursor::after(target, EventSeq(7)) })` keeping original `cursor` (not `ChangeFeedPage { events: [], next_cursor }`).
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

## Evidence Class Definitions and Three-Layer Evidence Table (normative for Stage-2)

| Layer | Allowed use | Disallowed substitution | Current effective rows |
| --- | --- | --- | --- |
| Test-only driver | Controlled `Runtime`, `WorkStore`, `Scheduler`, `Storage`/restart seams and deterministic `CognitiveExecutor` establish fixtures, failures, Work, claims/fences, projections/blobs, competitors and recovery boundaries. | Driver state, internal structs, SQL, or executor return values cannot be acceptance evidence. | CV-017, CV-018, CV-019, CV-028, CV-029, CV-034..CV-037 |
| Public observable evidence | `LoomClient` formal `HistoryService`, `QueryService`, `IngressService`, `AdminService::timeline_logical_status`, session/provenance, Facet/blob/reference, and other existing `loom-api`/`loom-client` reads establish Pass/Fail/Unavailable. | Internal Runtime/Storage reads and direct SQL cannot establish a Validator result. | Every current Pass/Fail/Unavailable conclusion |
| Product API / architecture gap | Use only when Runtime authority/semantic is absent, existing controlled fixtures cannot drive it, and no formal read can observe it. | Missing production-consumer setup/injection API alone is not a gap and is not an Unsuitable Reason. | CV-028 and CV-029 are blocked by `no existing formal semantic projection observable` / `no existing formal blob/reference fetch observable`; this is a formal-read gap, not a product-API amendment request. |

- **External** — generic `LoomClient` against `LOOM_VALIDATOR_BASE_URL` without `BackendHarness::connect` controlled construction. `BackendEvidence::External` (`validator:scenario:external`). Never trusted for `required-live` or `controlled restart` gates. May be backed by any implementation; `LOOM_TEST_POSTGRES_URL` never upgrades `External` (VALR-T04).
- **controlled InMemory** — `BackendHarness::connect(BackendKind::InMemory, base_url)` or `BackendContext::for_test_api` with `InMemory` kind + explicit `with_controlled_boundary_restart` where needed. `BackendEvidence::InMemory` trusted for logical correctness but not for durability across real restart (except via `InMemoryServer::restart` harness which preserves store and rebuilds boundary).
- **controlled PostgreSQL** — `BackendHarness::connect(BackendKind::PostgreSQL, base_url)` with valid `LOOM_TEST_POSTGRES_URL` (postgres://) and live endpoint reachable (`catalog()` succeeds). `BackendEvidence::PostgreSQL` trusted. `required-live` policy accepts only this class (`VALR-T06`).
- **controlled restart** — `BackendContext::restart()` path where `RestartCapability::ControlledBoundaryRestart` (VALR-T05). Generic `ReconnectOnly` cannot pass `CV-003/004/014/018/019/022/023/037/039/040` restart-sensitive assertions; must return `Unavailable` with `reconnect-only` evidence.

## PostgreSQL Live Requirement Rationale

Mandatory `Yes` where durability, persistence, or concurrency correctness cannot be observed via `External`/`InMemory` alone:

- `Yes`: CV-014, CV-016, CV-022, CV-023, CV-030, CV-031, CV-032, CV-033, CV-039, CV-040 (10 rows). Rationale in per-row table.
- `No — blocked`: CV-028 and CV-029 are blocked because no existing formal semantic projection or blob/reference fetch observable exists. PG cannot substitute for a missing `LoomClient` surface.
- `No`: the remaining 17 current No rows (CV-012, CV-013, CV-015, CV-017, CV-018, CV-019, CV-020, CV-021, CV-024, CV-025, CV-026, CV-027, CV-034, CV-035, CV-036, CV-037, CV-038) use controlled drivers and public observations; they are not blocked by missing production-facing setup/injection APIs and may use PG when available.

The prior candidate's `No — blocked` labels for nine rows are retained only in
the historical record above. They are not the current blocked count; current
`No — blocked` is exactly CV-028/CV-029.

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
8. **Semantic projection rebuild (CV-028 current effective contract)** — the Runtime-owned projection/storage fixture may build, clear, and rebuild the derived projection as test-only setup/control. The only existing formal reads are `LoomClient` `HistoryService::list_events` and `QueryService::get_facet`; `SemanticIndexDescriptor` is catalog metadata only, and no formal SemanticProjection read/rebuild/delete surface exists. Current result is blocked: `no existing formal semantic projection observable`. This is a formal-read gap, not an Architecture Amendment conclusion.
9. **Blob reference fetch (CV-029 current effective contract)** — the Runtime-owned blob/storage fixture may create and clear a referenced blob as test-only setup/control. The only existing formal reads are `LoomClient` `QueryService::get_facet` and `HistoryService::list_events`; `FacetSnapshot.value` is opaque `Value`, and no formal blob fetch/read surface exists. Current result is blocked: `no existing formal blob/reference fetch observable`. Internal BlobStore/SQL cannot serve as acceptance evidence, and this is a formal-read gap, not an Architecture Amendment conclusion.
10. **Pinned read inventing API (CV-030 corrected)** — previous draft invented `get_facet_at_version`/`BaseWorldView`/`ResolutionContext`; corrected to existing `TimelineService::fork(ForkTimelineRequest::at_version)` + `QueryService::get_facet` on fork target. `CV-030` remains implementable via this existing path; CV-028/CV-029 remain blocked on the formal-read gaps recorded above. Their old blocked wording remains historical only.
11. **Ingress failure boundary (CV-017 current effective contract)** — the controlled `Runtime`/`Ingress`/`Storage` seam drives `Retryable(IngressTechnicalFailure)` and recovery; `LoomClient` `IngressService::ingress_status` plus `HistoryService`/`QueryService` observe it. No production fault-injection endpoint is required.
12. **Scheduler claim/head boundary (CV-018 current effective contract)** — controlled `Scheduler`/`WorkStore`/`Runtime` drives ordered Work and claims; formal `timeline_logical_status` and `HistoryService` observe order. No production `schedule_work`/`claim` endpoint is required.
13. **Stale fence boundary (CV-019 current effective contract)** — controlled `Scheduler`/`WorkStore` drives stale/new fence or lease competitors; formal logical status, completion/history, and provenance reads observe rejection and winner. `terminalize_work` remains termination-only and is not used as a claim driver.
14. **Agency Decision boundaries (CV-034/035/036 current effective contract)** — controlled Agency/Runtime fixture injects deterministic `CognitiveExecutor` Decisions and drives Wake execution; formal logical status, history, query, and session/provenance reads observe NoAction, Act, or Rejected. `cognition: String` remains a request field; no public Decision-injection API is required.
15. **Concurrent Agency CAS (CV-037 current effective contract)** — controlled Agency/Runtime fixture creates stale/new CAS or fence competitors; formal logical status, history, query, and provenance reads observe winner/loser and no overwrite. No production claim API is required.
16. **Current effective blocked rule** — these driver/read seams are not blocked merely because they are not production-consumer APIs. If a future implementation proves a Runtime authority/semantic or formal observable is absent, record that concrete gap and mark only the affected row blocked.
17. **Historical distinction** — the old nine gap statements remain in the append-only historical candidate record and must not be mixed into the current effective coverage count.

No new capability scenario invented beyond T10–T18 intents above; any additional need requires Architecture Amendment before coverage claim.

## Stop Conditions / Blocked Rows

- If a required scenario cannot be specified without a new authority/semantic decision, mark that matrix row `blocked` and escalate. Do not invent the missing architecture in T08.
- The historical candidate recorded 9 blocked rows (`CV-017`, `CV-018`, `CV-019`, `CV-028`, `CV-029`, `CV-034`, `CV-035`, `CV-036`, `CV-037`) under the pre-policy rule; that count is preserved only for audit. Under the current effective policy, CV-017/CV-018/CV-019/CV-034/CV-035/CV-036/CV-037 are suitable, while CV-028/CV-029 remain blocked on their formal-read gaps: current `CV-012..CV-040` is **27 suitable / 2 blocked**, and current `CV-001..CV-040` is **38 suitable / 2 blocked**. These counts must not be mixed.
- A current row is `blocked` when the required Runtime authority/semantic, existing controlled driver, or existing public/formal read needed for the assertion is absent. Missing production `schedule_work`, `claim`, fault-injection, Decision-injection, or Work-execution endpoints alone do not trigger a block. CV-028/CV-029 are the current exceptions because their required formal semantic-projection and blob/reference observables do not exist; internal projection/blob state and SQL cannot replace them. No new authority or product API is invented.
- If during T10–T18 implementation a public API cannot observe a required fact without inventing a new authority surface, stop and report coverage gap for architecture review (per each leaf's Stop Conditions).

## Conclusion — current versus historical candidate

The pre-policy candidate remains an append-only historical result of 31
suitable / 9 blocked, with its original evidence, date, completion PR and
merge SHA retained above. The correction changes only the effective evidence
contract: controlled Runtime/Scheduler/Storage/Agency drivers perform setup,
while `LoomClient` formal reads provide observable evidence. Missing
production-facing setup or injection endpoints are not architecture gaps.
CV-028 and CV-029 remain current blocked rows because the formal semantic
projection and blob/reference observables do not exist. The current effective
count is **27 suitable / 2 blocked** for `CV-012..CV-040` (**38 suitable / 2
blocked** for `CV-001..CV-040`); no historical and current count is mixed.

No new Loom authority, semantic, Scheduler, Agency meaning, product API, or
scenario is introduced by this ledger correction.

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

## Historical Candidate Verification Evidence (preserved)

The entries in this section are the prior candidate's recorded verification
claims and are retained as historical audit material, not as evidence for the
current correction.

- `python3 tools/validator_ready.py --root docs/tasks/validator-recert/stage-1 --check --format json` → `valid=true`, `violations=[]`, `record_count=7`, `ready=[]`, `blocked=[]` (all VALR-T01..T07 completed).
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert/stage-2 --check --format json` → See Progress Log note on cross-stage dependency: isolated root reports dependency `312` has no task metadata because that Stage-1 record is not under `stage-2`. When checked at `docs/tasks/validator-recert` (both stages) → `valid=true` after this ledger is added with `in_progress`. See command below.
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json` → expected `valid=true`, `violations=[]` (T08 `in_progress` with satisfied dependency `312` completed).
- `python3 tools/check_architecture.py` → `Loom architecture dependency policy: OK`
- `python3 tools/check_storage_sql_ownership.py` → `storage SQL ownership check passed`
- `cargo fmt --all -- --check` → pending CI; local pre-merge candidate must run `cargo fmt --all`, `cargo check`, `cargo clippy`.

## Historical Candidate Acceptance (preserved)

- [x] Every new CV ID has exactly one owner leaf (table above; 29 IDs, disjoint).
- [x] Every planned scenario has expected/public-surface/evidence/prerequisite fields (per-CV specifications).
- [x] Existing CV-001..011 remain stable (verification section).
- [x] Matrix identifies explicit coverage gaps rather than hiding them (Coverage Gaps section, 17 items, 9 blocked CV-017/018/019/028/029/034/035/036/037).
- [x] Reviewer confirms the matrix is implementable without semantic guesswork (Reviewer `01a03f69-80db-737c-beba-540324a07ecf` on head `64960df` — D-010/D-011/D-012 closed, AC-1~AC-6 passed).
- [x] CI/docs checks complete before marking completed (canonical `validator_ready` PASS, `check_architecture`/`check_storage`/`fmt`/`diff --check` PASS; PR #343 required checks `Rust checks`/`PostgreSQL 18` SUCCESS on `64960df`).

The checklist above is the historical candidate's acceptance record and is not
reused as acceptance evidence for this correction. Current correction
acceptance is tracked separately:

## Current Correction Acceptance

- [x] Driver, public observable evidence, and product API/gap are distinct in the policy, current overview, and nine detailed rows.
- [x] CV-017/CV-018/CV-019/CV-034..CV-037 have current effective contracts with precise existing fixture seams and formal observations; CV-028/CV-029 have precise test-only drivers and are explicitly blocked because their required formal reads are absent.
- [x] Historical 31/9 blocked accounting, old evidence wording, completion PR, merge SHA, date, and basis remain separately identified.
- [x] Current blocked accounting is independent: `CV-012..CV-040` = **27 suitable / 2 blocked** (blocked exactly CV-028/CV-029); full `CV-001..CV-040` = **38 suitable / 2 blocked**.
- Reviewer independently verifies the current correction candidate: pending Leader scheduling.
- Required checks for this correction are recorded below after execution; this ledger does not claim Reviewer or CI acceptance.

## Progress Log

- 2026-08-27 — Created `docs/tasks/validator-recert/stage-2/t08-coverage-matrix.md` as contract-only leaf with `status: in_progress`, `depends_on: [312]`, empty `completed_at`/`completion_pr`/`merge_sha`. Froze `CV-012..CV-040` allocation with no conflict (production registry at `d4437fb` contains `CV-001..CV-011`; `CV-012` in `reports.rs` test helpers is not a production registration). Specified per-scenario capability clause, preconditions/fixtures, formal `loom-api` surfaces (`WorldService`/`ActionService`/`IngressService`/`TimelineService`/`QueryService`/`HistoryService`/`CatalogService`/`SubscriptionService`/`AdminService`), expected results, evidence classes, PostgreSQL mandatory flags, owners, complementary core/M13 evidence, and unsuitable reasons. Ensured parallel-safe suite ownership for T09 and escalatable blocked marking. Noted cross-stage `validator_ready` nuance: `--root stage-2` isolated check cannot resolve dependency `312` (lives under `stage-1`); canonical combined `--root docs/tasks/validator-recert` validates correctly. No production code, registry, or T01–T07 files modified.
- 2026-08-27 — Post-merge ledger audit (merge commit `276981290b4d4b8b8d0299402944c5f75cbb9a69` from PR #343 head `64960df540cfab9159648200f26b73e0a114d46b`): set `status: completed`, `completed_at: 2026-08-26`, `completion_pr: 343`, `merge_sha: 276981290b4d4b8b8d0299402944c5f75cbb9a69`, checked Acceptance `Reviewer`/`CI` boxes; Reviewer `01a03f69-80db-737c-beba-540324a07ecf` on `64960df` passed D-010/D-011/D-012 and AC-1~AC-6, `gh pr checks 343` `Rust checks`/`PostgreSQL 18` SUCCESS; canonical `validator_ready` `valid=true`/`violations=[]` (8 records, `VALR-T08` ready) confirmed. No matrix/CV allocation/T09/T01–T07 changes.
- 2026-08-28 — Correction audit requested by Leader comment `01a047a2-396e-75f2-9ddd-eec9ce0515e9`, effective against Loom main baseline `95f7e7a0233cfa917d0c9656b990fd2af4996874`. Preserved the historical 31 suitable / 9 blocked candidate and completion/merge facts; separated test-only driver, public observable evidence, and product API/architecture-gap policy. Rewrote the current effective contracts for CV-017/CV-018/CV-019/CV-028/CV-029/CV-034..CV-037 with existing Runtime/WorkStore/Scheduler/Storage/Agency controlled seams and `LoomClient` formal reads. The superseded pre-review correction candidate reported 29 suitable / 0 blocked for CV-012..CV-040; that candidate is retained as audit history only and is not the current result. No new authority, product API, registry, or scenario. Required command evidence for the corrected candidate is recorded in the next entry.
- 2026-08-28 — Required correction checks executed against this candidate: `python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json` **FAIL** (`valid=false`) only because unrelated T19–T21/T24 dependency records are not completed; T08 itself has no violation after the correction. `python3 tools/check_architecture.py` **PASS** (`Loom architecture dependency policy: OK`); `python3 tools/check_storage_sql_ownership.py` **PASS** (`storage SQL ownership check passed`); `cargo fmt --all -- --check` **PASS**; `git diff --check` **PASS**. No CI or Reviewer result is claimed.
- 2026-08-28 — Final-candidate command rerun after exact fixture-seam wording: same result and evidence (`validator_ready` **FAIL** only on unrelated T19–T21/T24 dependency eligibility; T08 has no violation; `check_architecture.py`, `check_storage_sql_ownership.py`, `cargo fmt --all -- --check`, and `git diff --check` **PASS**). This entry corresponds to the final single-file diff below; no CI or Reviewer result is claimed.
- 2026-08-28 — Post-amend final candidate verification: `validator_ready` **FAIL** with `valid=false`, 11 unrelated T19–T21/T24 dependency violations and 0 T08 violations; `check_architecture.py`, `check_storage_sql_ownership.py`, `cargo fmt --all -- --check`, and `git diff --check` **PASS**. This is the final required-check result for the amended candidate; no CI or Reviewer result is claimed.
- 2026-08-28 — Leader return decision `01a047cf-b3db-7e81-913a-d42882013553` accepted Reviewer defects D-001/D-002: CV-028/CV-029 are current blocked rows with exact formal-read gaps (`no existing formal semantic projection observable` / `no existing formal blob/reference fetch observable`), while the other seven corrected rows remain suitable. Current accounting is `CV-012..CV-040` = **27 suitable / 2 blocked** and `CV-001..CV-040` = **38 suitable / 2 blocked**; historical 31/9 and the superseded 29/0 candidate remain separately labeled audit history. Final local checks for this correction: canonical `validator_ready` **FAIL** (`valid=false`, `record_count=22`, 11 T19/T20/T21/T24 dependency violations, T08 violations=0); `check_architecture.py`, `check_storage_sql_ownership.py`, `cargo fmt --all -- --check`, and `git diff --check` **PASS**. No CI or Reviewer result is claimed.
