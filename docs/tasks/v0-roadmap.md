# Loom Engine V0 Implementation Roadmap

Status: **historical implementation baseline** — M4–M13 implementation and the historical final candidate are integrated. Current-main V0 re-certification is tracked separately and remains in progress, pending until T25.
Replanned: 2026-08-22  
Architecture baseline: accepted Amendments 0001–0003 + `docs/architecture/README.md` reverse supersession table.

This roadmap supersedes the unmerged historical M4–M13 planning from issues #60–#134 and draft PR #135. Milestones 1–3 remain historically completed and are not rewritten; M4 begins with an explicit reconciliation of their implementation against the current architecture.

## Current-main re-certification boundary

The production candidate under re-certification is
`4efb1d346c926f2ee10654c3bc24cd92af351881`, merged by PR #375. Current `main`
is `6da9989eb9298aa9739a6aa681fbdb8cd9dcde4d`, with current-candidate
evidence-only descendants merged by PRs #376 (T23), #377 (T22), #378 (T24) and
#379 (T19). T19/T20/T22/T23 are recorded as done; T24 remains blocked
fail-closed because CV-028 and CV-029 are still real manifest capability gaps.
The prior `95f7e7a...` candidate, older PR results and `31 Pass / 9 Unavailable`
/
`gate_passes: false` records remain historical/non-current. Re-certification
remains **pending until T25**; Stage 3 and its root checklist stay open.

## Planning rules

1. Read `docs/architecture/README.md` first and resolve reverse supersession before implementing a task.
2. If a task derives from amended baseline text, use both the baseline clause and accepted Amendment as its acceptance source.
3. Implementation tasks do **not** make new authority/semantic architecture. A genuinely missing architecture decision requires an Architecture Amendment first.
4. Each implementation task has one GitHub Issue and one `docs/tasks/<milestone>/...` record.
5. A task is complete only with acceptance, PR, merge SHA and verification/CI evidence in both the task ledger and Issue state.
6. Required current CI/deployment baseline is Ubuntu/Linux. macOS is not a mandatory v0 gate.
7. PostgreSQL is a `loom-storage` implementation detail: schema DDL lives under `crates/loom-storage/migrations/`, runtime SQL under `crates/loom-storage/sql/`, and other crates/applications must not own SQLx/PostgreSQL access. Infrastructure prerequisite #209 enforces this before M5 expands the persistence surface.

## Historical baseline

M1–M3 already established valuable implementation assets: Core/Protocol types, Capability registry/schema validation, Runtime-owned validation/`ValidatedResolution`, candidate overlay, cross-Capability subresolution, unified `loom-api`, InMemory/PostgreSQL authority persistence, Timeline CAS, lease/fence/retry primitives, World/Timeline lifecycle and restart tests.

They are preserved as historical completion evidence. M4 migrates the assumptions that Amendments 0001–0003 later superseded or strengthened.

## V0 critical path

```text
M1–M3 historical implementation
        ↓
M4 #136  Architecture reconciliation foundation
        │   Event time / World Time
        │   World Runtime Binding
        │   Template birth
        │   minimum Runtime Revision + root Session/Assembly
        ↓
#209      Storage SQL ownership / centralized PostgreSQL implementation baseline
        ↓
M5 #137  Timeline Logical Runtime + deterministic Scheduler
        │   Work target/due/order
        │   Logical Journal
        │   FailurePolicy / head admission / chronology / quiescence
        │   Reaction / entropy / worker topology
        ↓
M6 #138  Deterministic replay + Timeline fork
        │   Event replay + Logical Journal replay
        │   ancestry / historical fork / branch causality
        ↓
M7 #139  Query + Catalog + semantic retrieval + blob + scalable pinned reads
        ↓
M8 #140  Durable Ingress + HTTP/SSE + formal client + loom-server
        ↓
M9 #141  Full Runtime Revision / Execution Provenance + Admin Control
        ↓
M10 #142 Agency + durable cognition
        │   restricted AgentWorldView
        │   Agency Wake / Decision / Action authority
        │   CAS reuse/resample policy
        ↓
M11 #143 Resource bounds + fault/property/security + capacity evidence
        ↓
M12 #144 CLI + neutral examples + operator/developer docs
        ↓
M13 #145 Integrated release gate + closure audit
```

## Why the old order changed

The previous roadmap placed Scheduler correctness, World Binding, Runtime Revision/Execution Session and Agency target semantics too late. Under the current architecture these are execution prerequisites, not optional later features:

- A World-scoped Action/Work cannot be correctly assembled before its immutable World Runtime Binding is known.
- Exact compatible implementations belong to a root Execution Session pinned to one active Runtime Revision.
- Replay/fork cannot be defined from Event rows alone because World Time, logical Work/order and chronology-budget position live in Timeline Logical State.
- Scheduler must select one Timeline logical head before operational claimability; it cannot scan for any claimable due row.
- Agency Wake is a distinct Scheduler Work target, not a Capability WorkHandler exception.
- M5–M10 add substantial PostgreSQL surface, so the storage implementation boundary must be mechanically enforced before those tasks begin rather than cleaned up after V0.

Therefore M4/M5 precede replay/fork and all server/Agency work, and #209 closes the storage-SQL organization prerequisite before M5's serial root.

## Milestone map

### M4 — Reconcile existing runtime with Amendments 0001–0003 (#136)

- #146 M4-T1 — Event occurrence authority + explicit World Time
- #147 M4-T2 — immutable World Runtime Binding + legacy migration
- #148 M4-T3 — Template validation + atomic World birth
- #149 M4-T4 — minimum Runtime Revision ledger
- #150 M4-T5 — root Execution Session + exact Execution Assembly
- #151 M4-T6 — neutral Template/Binding fixtures
- #152 M4-T7 — reconciliation gate
- #209 M4-I1 — centralized PostgreSQL SQL ownership baseline (infrastructure prerequisite for M5)

**Exit:** existing M1–M3 execution/persistence/restart assets work under Runtime-stamped Event time, explicit World Time, immutable Binding and pinned Session/Revision assembly; PostgreSQL implementation ownership is centralized in `loom-storage` before M5 extends it.

### M5 — Timeline logical runtime + deterministic scheduler (#137)

Prerequisites: M4 gate #152 and storage SQL ownership #209.

- #153 M5-T1 — Work target/effective due/logical order
- #154 M5-T2 — Timeline Logical Journal
- #155 M5-T3 — bounded FailurePolicy + missing-implementation blockage
- #156 M5-T4 — logical-head admission + head-aware PostgreSQL claim
- #157 M5-T5 — Chronology Budget + quiescence + World-Time driver
- #158 M5-T6 — atomic Reaction scheduling
- #159 M5-T7 — Runtime-controlled entropy
- #160 M5-T8 — resumable scheduler worker + executor topology
- #161 M5-T9 — scheduler/liveness gate

**Exit:** same-Timeline Scheduler order is exactly `(effective_due_world_time, logical_schedule_order)`, later Work never skips a due head, technical operations remain outside Timeline logical history, failure paths are bounded, and World Time advances only through explicit quiescent Logical Commits.

### M6 — Deterministic replay + Timeline fork (#138)

- #162 M6-T1 — frozen-Event materialized State replay
- #163 M6-T2 — Timeline Logical State replay
- #164 M6-T3 — ancestry/EventRef + head fork
- #165 M6-T4 — historical fork
- #166 M6-T5 — ancestry-aware History/causality
- #167 M6-T6 — replay/fork isolation gate

**Exit:** arbitrary committed TimelineVersion reconstructs semantic State + World Time + logical Future/budget without re-running code; historical fork preserves Binding and clones branch-local Pending obligations correctly.

### M7 — Query, catalog, semantic retrieval + blob foundations (#139)

- #168 M7-T1 — Binding-aware Catalog + history/trajectory/causal queries
- #169 M7-T2 — semantic indexes + PostgreSQL pgvector projection
- #170 M7-T3 — Runtime-mediated semantic retrieval + ReadSet evidence
- #171 M7-T4 — immutable Blob/Object Store
- #172 M7-T5 — scalable Pinned Read Boundary
- #173 M7-T6 — read/projection/blob authority gate

**Exit:** projections and blobs are useful but rebuildable/non-authoritative, World catalog respects Binding, and representative PostgreSQL reads no longer require full-World eager materialization.

The previous standalone generic `Event Scope` proposal is intentionally excluded because it is not currently frozen by the canonical architecture. It requires a future Amendment if promoted.

### M8 — Durable Ingress + HTTP/SSE boundary + server (#140)

- #174 M8-T1 — transport-neutral Ingress/Subscription contracts
- #175 M8-T2 — durable idempotent Ingress persistence
- #176 M8-T3 — Ingress through normal Session + Action authority
- #177 M8-T4 — resumable committed Change Feed
- #178 M8-T5 — `loom-boundary` HTTP/JSON + SSE
- #179 M8-T6 — formal HTTP client
- #180 M8-T7 — `apps/loom-server`
- #181 M8-T8 — service black-box/restart gate

**Exit:** Loom runs as a restartable Linux service; accepted Ingress is not World Truth, all mutation still enters normal Runtime authority, and SSE resumes from committed history.

### M9 — Runtime provenance + operator control (#141)

- #182 M9-T1 — complete immutable Runtime Revision history
- #183 M9-T2 — complete Execution Session provenance
- #184 M9-T3 — atomic Event↔Session linkage
- #185 M9-T4 — isolated Admin / Runtime Control API
- #186 M9-T5 — upgrade/provenance/control gate

**Exit:** Event → Session → Runtime Revision/implementation/read/call/entropy evidence is durable; Admin controls use defined Runtime authority rather than database mutation.

### M10 — Agency + durable cognitive execution (#142)

- #187 M10-T1 — `loom-agency` contracts from Amendment 0003
- #188 M10-T2 — visibility-limited Runtime AgentWorldView builder
- #189 M10-T3 — CognitiveExecutor gateway + deterministic fake
- #190 M10-T4 — atomic Agency Wake Decision/Action commit
- #191 M10-T5 — Wake scheduling/resume + CAS policy
- #192 M10-T6 — Agency gate

**V0 R-1 rule:** semantic rejection of `Decision::Act` MUST complete the current Wake as a determined no-world-change outcome. Reconsideration is a new Wake. Technical cognition failure remains bounded FailurePolicy.

**CAS policy:** default v0 behavior is explicit `resample` after a cognition result loses Timeline-wide CAS, unless a specific deterministic/reusable policy is configured. Any reuse must be provenance-visible and revalidated against the fresh pinned version.

### M11 — Resilience, resource bounds + capacity evidence (#143)

- #193 M11-T1 — resource bounds
- #194 M11-T2 — property/fault/dependency-security gates
- #195 M11-T3 — scheduler/Agency capacity benchmarks
- #196 M11-T4 — worker/executor stress + Linux CI hygiene
- #197 M11-T5 — hardening/capacity gate

**Exit:** no unbounded amplification path remains accidental; actual single-Timeline/multi-Timeline/cognition capacity is measured and documented. Timeline-wide successful logical commit serialization remains the v0 correctness model; fine-grained commit validation is deferred.

### M12 — CLI, examples + documentation (#144)

- #198 M12-T1 — official `loom-cli`
- #199 M12-T2 — V0 operator/developer docs + quickstart
- #200 M12-T3 — neutral public examples
- #201 M12-T4 — public-consumer rehearsal gate

**Exit:** a new user can reproduce the supported system through public server/client/CLI surfaces only.

### Historical M13 — V0 release + closure audit (#145)

The following entries preserve the historical M13 release candidate and
closure-audit evidence. They do not certify the current `main` checkout; the
separate current-main recertification remains pending until T25.

- #202 M13-T1 — integrated V0 release gate
- #203 M13-T2 — final task/Issue/evidence closure audit

**Historical exit:** The M13 record declared its historical release sequence
complete after #203. Current-main V0 re-certification is a separate process and
must not be declared complete before T25.

## Capacity assumptions carried into implementation

- Scheduler-managed semantic execution for one Timeline is logical-head ordered. A large same-WorldInstant batch therefore incurs the sum of those Work execution times on that Timeline; parallelism comes primarily from independent Timelines and pre-commit work that still loses/commits via Timeline-wide CAS.
- Slow cognition may be wasted when another commit wins before a Wake commits. M10/M11 must measure that waste and expose the selected reuse/resample policy in provenance.
- A Pinned Read Boundary is a consistency contract, not a mandate to load an entire World. M7 must demonstrate a bounded non-full-snapshot PostgreSQL realization.

## Explicit v0 non-goals / deferred unless promoted

- fine-grained ReadSet/MVCC commit acceptance replacing Timeline-wide CAS;
- checkpoint acceleration as a correctness dependency;
- arbitrary hundred-thousand-Agent same-Timeline write-throughput claims;
- dynamic per-World hot-plug/Binding mutation;
- vendor LLM/provider as a V0 correctness requirement;
- dynamic native/WASM plugin ABI;
- dedicated graph database;
- distributed/multi-database authority;
- GPUI Studio as a blocking Engine V0 requirement;
- generic Event Scope mechanism without an accepted Amendment.

## Execution order

Default to the dependency graph, not issue number. Parallel work is allowed only when task dependencies and file/contract ownership are disjoint. A milestone final gate runs after all blocking children are merged on one common baseline. PostgreSQL-bearing tasks must preserve the #209 storage ownership boundary.
