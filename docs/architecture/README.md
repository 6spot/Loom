# Loom Architecture Index

> Status: **normative document authority map for Loom v0.**
>
> 本文不重复具体 Runtime/World 规则。它只回答四个问题：**哪份文档对什么主题有最终解释权、发生冲突时如何裁决、哪些 frozen 条款已被 Amendment 取代、当前有哪些 deferred decisions。**

## 1. Document authority

Loom 不再把多份“规则摘要”视为彼此独立的规范源。每个主题只有一个 canonical owner。

| Topic | Canonical source |
| --- | --- |
| Core primitives / admission / World mechanism | `core.md` |
| Product semantic layers / ownership | `layers.md` |
| World Runtime Binding / World Time / Logical Commit / Execution Session / scheduler chronology baseline | `world-runtime.md` |
| Detailed Runtime ↔ Capability execution protocol | `runtime-contracts.md` |
| Software evolution / Runtime Revision semantics | `evolution.md` |
| Rust dependency DAG / public exposure / authority type placement | `governance.md` |
| Technical realization / persistence / dependency choices | `implementation.md` |
| Cross-cutting vocabulary | `glossary.md` |
| Accepted changes to a frozen baseline | `amendments/*.md` in amendment-number order |

`principles.md` is explanatory philosophy, **not an independent numbered normative rule set**. `AGENTS.md` is an execution guardrail/index, **not an independent architecture specification**. Root `README.md` is a navigation/status surface.

Within a canonical document, end-of-document invariant/acceptance summaries are navigation/checklist aids. They do not outrank that document's detailed topic sections or accepted Amendments.

## 2. Precedence

When two documents appear inconsistent, apply this order:

1. A later accepted Architecture Amendment overrides the exact baseline clauses it names.
2. For Rust dependency direction, public exposure and authority type placement, `governance.md` wins unless an accepted Amendment explicitly changes those rules.
3. For a topic owned by one canonical document in the table above, that canonical detailed topic section wins over summaries elsewhere.
4. `glossary.md` controls terminology only; it does not create Runtime authority by itself.
5. `implementation.md` may choose a realization only inside the semantic/authority constraints defined by the architecture documents.
6. End-of-document summary/checklist sections do not create another specification layer.
7. `principles.md`, `AGENTS.md`, README summaries and examples never override canonical contracts.

A conflict must be fixed in documentation before implementation. Do not silently choose whichever sentence is convenient.

## 3. Frozen baseline and accepted amendments

The Loom v0 World Runtime baseline was frozen at commit `a2238f05e649dc30ce21da1e1cb321bc2784e895`.

Accepted amendments are part of the current baseline from their merge point onward:

- `amendments/0001-runtime-liveness-and-boundaries.md` — Work failure exit, same-World-Time liveness budget, scheduler driver ownership, `SKIP_LOCKED` scope, Event occurrence-time ownership, Ingress contract, Template technical placement and terminology reconciliation.
- `amendments/0002-supersession-and-authority-linkage.md` — exact supersession mapping, one claimability contract, Chronology Budget authority placement, current CI baseline, missing-implementation observability and Amendment linkage rules.
- `amendments/0003-agency-execution-and-pinned-read-boundary.md` — autonomous Agent-wake execution closure, target-specific Scheduler admission for Agency Wake, AgentWorldView production authority, scalable pinned-read semantics, explicit Timeline-wide commit serialization and scale-related deferred decisions.
- `amendments/0004-derived-resource-public-read-boundary.md` — narrow Runtime-mediated `QueryService` reads for semantic projections and exact blob references; no projection/blob mutation surface or Storage authority is exposed.
- `amendments/0005-automatic-bounded-timeline-discovery.md` — bounded operational discovery of Scheduler Timeline targets after startup; Runtime retains logical-head, Work-claim, World-Time and semantic-commit authority.
- `amendments/0006-application-owned-product-persistence.md` — separates Loom engine PostgreSQL authority from explicitly registered Application-owned product persistence; Chronicle is the first narrow registration and remains isolated from Loom Runtime/World/Timeline storage authority.

A frozen document does not mean “never change.” It means changes are explicit, reviewable Amendments rather than silent edits that make history impossible to audit.

### 3.1 Reverse supersession lookup

Before using a frozen baseline section as an implementation requirement, check this table.

| Baseline document | Affected sections | Current authority |
| --- | --- | --- |
| `core.md` | §2.1, §4.3 | Amendment 0001 §8.3 — Actor/Agent are roles over Entity, not required Core persisted subtypes |
| `core.md` | §7.3 | Amendment 0001 §8.2 — Trigger is an umbrella; Temporal Trigger = `WorkSchedule::At`, Event Trigger = Reaction → Immediate Work |
| `core.md` | §8.4 | Amendment 0001 §8.1 — no generic Runtime `Intent` protocol type |
| `core.md` | §9.2 | Amendment 0001 §2 + Amendment 0002 §3 — work/reaction/compute budget reference is concretized by the reconstructable same-World-Time Chronology Budget contract |
| `world-runtime.md` | §5.1, §10.4 | Amendment 0003 §3 — Agent wake is a Scheduler-managed durable obligation; Runtime owns wake/session orchestration while Agency owns subjective context/cognition contracts |
| `world-runtime.md` | §6.4 | Amendment 0001 §5 — Runtime owns authoritative Event occurrence-time stamp |
| `world-runtime.md` | §8.1 | Amendment 0001 §9 + Amendment 0002 §2 + Amendment 0003 §3.2 + Amendment 0005 §3.1–§3.2 — common claim/admission rules remain Runtime-owned; discovery is a separate operational observation and must retain future/temporarily unclaimable Pending Work |
| `world-runtime.md` | §8.7–§8.9 | Amendment 0005 §3.1–§3.5 — the official server may discover Timeline targets dynamically; discovery is not ordering, a queue or a second World/Timeline authority path |
| `world-runtime.md` | §2.4 | Amendment 0002 §3 — chronology-budget consumption is Timeline Logical State |
| `world-runtime.md` | §13 | Amendment 0002 §7 — status changed: end-of-document hard invariants are navigation/checklist aids, not an independent specification layer |
| `runtime-contracts.md` | §1, §6.3, §6.5 | Amendment 0003 §3 — closes wake admission/session lifecycle and AgentWorldView production authority |
| `runtime-contracts.md` | §5.6, §14.1, §14.7 | Amendment 0003 §3.1–§3.5 — Capability Work still uses WorkHandler; Agency Wake is a distinct Scheduler Work target with Agency-specific compatibility and atomic completion semantics |
| `runtime-contracts.md` | §7.1, §16.3 | Amendment 0003 §5 — successful logical commits serialize at Timeline scope; Scheduler Work still admits only the logical head; fine-grained commit validation remains deferred |
| `runtime-contracts.md` | §16.5 | Amendment 0003 §4 — pinned `BaseWorldView` is a consistency contract, not a requirement to eagerly materialize the complete World in memory |
| `runtime-contracts.md` | §9.5, §10.1, §16.1 | Amendment 0001 §5 — Capability does not choose authoritative `occurred_at` |
| `runtime-contracts.md` | §14.10–§14.11 | Amendment 0001 §9 + Amendment 0002 §2 + Amendment 0003 §3.2 + Amendment 0005 §3.1–§3.4 — Runtime due/claimability remains unchanged; discovery cannot claim, reserve or filter away future/blocked Pending Work |
| `runtime-contracts.md` | §14.16–§14.17 | Amendment 0005 §3.1–§3.2, §3.5 — discovered future Work may be inspected for legal explicit advancement, which remains Runtime-owned |
| `runtime-contracts.md` | §17.2 | Amendment 0001 §6.2 + Amendment 0004 §3–§5 — public API includes Ingress plus provider-neutral semantic-projection and exact blob-reference reads mediated by Runtime |
| `runtime-contracts.md` | §20.2 | Amendment 0001 §7 — Runtime owns Template validation / ValidatedWorldBirthPlan authority |
| `runtime-contracts.md` | §22 | Amendment 0002 §7 — status changed: normative-rule summary is a navigation/checklist aid, not an independent specification layer |
| `governance.md` | public exposure rules | Amendment 0004 §5 + Amendment 0006 §5 — Loom engine semantics remain behind Loom API/Runtime; a product API may expose only independently Application-owned product data and cannot become a hidden Loom engine path |
| `governance.md` | §5.3, §6 | Amendment 0006 §3–§4 — `loom-storage` remains exclusive for Loom engine/Runtime PostgreSQL authority; explicitly registered Application product persistence may own an isolated product database/schema, migrations and adapter |
| `governance.md` | §7, §9, §10 | Amendment 0006 §3–§5 — Application-owned product persistence/API is allowed only for Application authority; Loom semantic operations still use Loom API and Applications never gain engine storage authority |
| `governance.md` | §15 | Amendment 0002 §7 — status changed: normative-rule summary is a navigation/checklist aid, subordinate to accepted Amendments and detailed governance sections |
| `governance.md` | §4.3, §10 | Amendment 0005 §3.5 — Application composition roots may host bounded dynamic target discovery without acquiring semantic Scheduler/World-Time authority |
| `implementation.md` | §3 | Amendment 0001 §7 — Template/Birth technical placement |
| `implementation.md` | §5.1 | Amendment 0001 §6.2 + Amendment 0004 §3–§5 — public API includes Ingress plus the two narrow derived-resource reads |
| `implementation.md` | §6.5, §13/§13.3 `SKIP LOCKED` statements | Amendment 0001 §4 — `SKIP_LOCKED` may distribute across independent Timeline heads but must never skip a logical head within one Timeline |
| `implementation.md` | §11.5 | Amendment 0003 §5 — optimistic TimelineVersion CAS implies Timeline-wide successful-commit serialization in v0 |
| `implementation.md` | §13.1, §13.2 | Amendment 0003 §3.2 — logical Work target/compatibility is target-specific for Capability Work vs Agency Wake while due/order/status remain shared |
| `implementation.md` | §15.2, §16 | Amendment 0003 §3 — Agency cognition tail is preceded by durable wake/session/context orchestration |
| `implementation.md` | §16 | Amendment 0004 §3 — semantic projection reads may be consumed externally only through the Runtime-mediated provider-neutral `QueryService` contract |
| `implementation.md` | §12.2, §21.5 | Amendment 0001 §5 — Runtime-stamped Event occurrence time |
| `implementation.md` | §12.3 | Amendment 0001 §9 + Amendment 0002 §2 + Amendment 0003 §3.2 — common claim/admission contract plus target-specific Agency-Wake compatibility |
| `implementation.md` | §4.2 | Amendment 0005 §3.5 — `loom-server` may host bounded target discovery while Runtime still owns next-Work/head and semantic transitions |
| `implementation.md` | §6.7, §12.6 | Amendment 0005 §3.2–§3.5 — discovery is bounded application plumbing, not World-Time policy or a deployment target-ID contract |
| `implementation.md` | §13.3 | Amendment 0001 §4 + Amendment 0005 §3.1–§3.4 — discovery precedes Runtime claim semantics and cannot add a reservation/skip path |
| `implementation.md` | §19 | Amendment 0002 §4 — current required CI platform is Ubuntu; macOS is not currently mandatory |
| `crates/loom-storage/sql/README.md` + storage SQL ownership enforcement | PostgreSQL ownership | Amendment 0006 §3–§6 — engine SQL remains `loom-storage`-exclusive; non-engine SQL is legal only inside explicitly registered Application product persistence roots, initially Chronicle |

Each accepted Amendment contains its own exact affected-clause index. If a row appears here, the frozen text is historical context, **not current executable acceptance criteria by itself**.

## 4. Open questions registry

Architecture-blocking open questions live **only here or in a referenced active Amendment**. Individual documents should not grow independent hidden TODO lists.

### Blocking before v0 re-planning

None, once all accepted Amendments listed above are merged.

### Deferred implementation decisions

These are intentionally not architecture blockers:

- exact numeric retry/backoff defaults;
- exact chronology budget numbers and optional additive dimensions such as reaction/derivation depth, total schedules or compute/cognition cost;
- exact Rust struct/function names where ownership is already fixed;
- PostgreSQL table names/index layout;
- Scheduler poll cadence/worker count;
- exact public authorization model for Runtime Admin operations;
- exact Agency Wake public/control DTO/service names and cadence policy;
- concrete pinned-read realization: revision-keyed cache, bounded prefetch, version-fenced lazy reads, miss/refill/restart, or a compatible combination;
- exact synchronous/async Rust host/view SPI syntax used to realize scalable pinned reads without leaking persistence authority;
- ReadSet-based fine-grained commit validation/concurrency beyond v0 Timeline-wide CAS;
- worker/process/executor topology and the coherent `Send`/`Sync` contract across API, Runtime ports, Capability/Agency SPIs and Storage adapters;
- historical replay/fork checkpointing and snapshot acceleration;
- large-World benchmark thresholds / readiness targets distinct from semantic architecture capability;
- dependency patch/minor versions not required by semantic compatibility;
- macOS CI restoration timing / exact cross-platform validation matrix;
- dynamic per-World Capability migration/hot-plug.

If one of these begins to affect semantic authority, replay/fork, deterministic ordering, World Binding or public contract ownership, promote it to an Architecture Amendment before implementation.

### Dependency adoption evidence

`implementation.md` may name a planned dependency/technology baseline before every item is present in the workspace. A dependency named there means **intended/allowed technical direction**, not proof that the repository already uses it.

Actual adoption is evidenced by the repository itself (`Cargo.toml`, `Cargo.lock`, imports/build integration and relevant acceptance tests). When planning work, distinguish:

```text
planned / approved dependency
!=
already adopted dependency
```

Do not report a dependency as implemented merely because it appears in architecture documentation.

## 5. Non-goal taxonomy

Do not maintain one giant duplicated “things we do not do” list.

- semantic/runtime non-goals belong in the canonical semantic document for that topic;
- Rust dependency/exposure prohibitions belong in `governance.md`;
- implementation technology defaults/rejections belong in `implementation.md`;
- temporary deferred decisions belong in this index.

## 6. Change procedure

For a material architecture change:

```text
problem / counterexample
        ↓
Architecture Amendment
        ↓
exact affected-clause index
        ↓
update Architecture Index reverse supersession table
        ↓
update glossary if terminology/authority meaning changed
        ↓
re-plan implementation
        ↓
code
```

Every accepted Amendment that supersedes or materially augments frozen text must name the exact document + section locations it affects.

Frozen baseline files may remain unchanged to preserve the historical snapshot; in that case the Amendment + this reverse supersession index are mandatory and must be consulted before converting baseline clauses into tasks.

Do not edit Issues/tasks/code first and backfill architecture later.
