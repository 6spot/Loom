# Architecture Amendment 0003 — Agency Execution and Pinned Read Boundary

> Status: **ACCEPTED for Loom v0 architecture baseline.**
>
> Depends on: `0001-runtime-liveness-and-boundaries.md`, `0002-supersession-and-authority-linkage.md`.
>
> This Amendment closes two gaps found after the v0 closure review: the missing orchestration path for autonomous Agent wake/cognition, and the accidental coupling between a pinned `BaseWorldView` and eager full-world in-memory materialization. It also records the v0 concurrency/scale consequences that must be visible during re-planning without redesigning Scheduler chronology.

---

## 1. Exact affected-clause index

Frozen baseline documents remain historical snapshots. This Amendment changes current interpretation through explicit linkage rather than silently rewriting the frozen files.

### 1.1 Frozen baseline clauses affected

| Baseline location | Baseline meaning | Current authority |
| --- | --- | --- |
| `world-runtime.md` §5.1 `Every root execution has one pinned software environment` | Lists `Agent wake / cognition-driven Action` as a root execution, but does not define how that root is scheduled, claimed, resumed or committed | **Materially augmented** by Amendment 0003 §3: Agent wake is a Scheduler-managed durable obligation with Runtime-owned orchestration and Agency-owned cognition contracts |
| `world-runtime.md` §8.1 operational claimability summary | Assumes the execution target is a Capability handler and predates Agency Wake target-specific compatibility | **Already superseded** by Amendment 0001 §9 + Amendment 0002 §2, and **further augmented** by Amendment 0003 §3.2 for Agency Wake |
| `world-runtime.md` §10.4 `Cognition remains an Agency boundary in v0` | Defines cognition → Decision → Action, but not the preceding wake/context/session lifecycle | **Materially augmented** by Amendment 0003 §3 |
| `runtime-contracts.md` §1 `Runtime Contract Map` | Shows optional Agency before `Decision`, but leaves wake admission and crash/retry semantics implicit | **Materially augmented** by Amendment 0003 §3 |
| `runtime-contracts.md` §5.6 `WorkHandler` | Describes WorkHandler as the Durable Work resolution entrypoint, which can be misread as requiring every Scheduler Work target to be a Capability WorkHandler | **Qualified** by Amendment 0003 §3.1–§3.2: Capability Work uses WorkHandler; Agency Wake is a distinct Runtime-orchestrated Scheduler Work target and does not receive a generic Cognitive handle through WorkHandler |
| `runtime-contracts.md` §6.3 `AgentWorldView` | Defines the subjective view and its consumer, but not the producer/orchestration authority | **Materially augmented** by Amendment 0003 §3.4 |
| `runtime-contracts.md` §6.5 `Execution Session and Execution Assembly` | Pins controlled Agency services where relevant, but does not define the Agent-wake Session lifecycle | **Materially augmented** by Amendment 0003 §3.3–§3.7 |
| `runtime-contracts.md` §7.1 `ReadSet` | States v0 correctness uses Timeline-level CAS and future fine-grained validation may use observed ReadSet | **Clarified/augmented** by Amendment 0003 §5: v0 successful logical commits serialize at Timeline scope; fine-grained commit validation remains a deferred architecture change |
| `runtime-contracts.md` §14.1 `DurableWork` | Conceptual Work target is represented only by `WorkHandlerId` | **Materially augmented** by Amendment 0003 §3.2: Scheduler chronology must support target-specific Capability Work and Agency Wake semantics; exact Rust/persistence representation remains an implementation choice |
| `runtime-contracts.md` §14.7 `Completion Atomicity` | Generic Work completion explicitly verifies a Work owner Capability and compatible handler assumptions | **Qualified** by Amendment 0003 §3.2 + §3.5: Capability Work keeps owner/handler validation; Agency Wake validates Agency execution compatibility and atomically completes the wake with its determined outcome |
| `runtime-contracts.md` §14.11 operational claimability summary | Assumes owning Capability + handler implementation for every Work target | **Already superseded** by Amendment 0001 §9 + Amendment 0002 §2, and **further augmented** by Amendment 0003 §3.2 target-specific compatibility |
| `runtime-contracts.md` §16.3 `Commit Is the Linearization Point` | “Resolve/Cognition can run in parallel” can be misread as same-Timeline Scheduler Work parallelism | **Clarified** by Amendment 0003 §5: parallel pre-commit execution is allowed only where admission permits; successful logical commits remain Timeline-serialized and Scheduler Work still admits only the logical head |
| `runtime-contracts.md` §16.5 `Persistence Port Ownership` | Says Resolver/Invariant/WorkHandler read a Runtime-pinned **in-memory** `BaseWorldView`, which can be read as requiring eager full-world materialization | **Superseded only in materialization strategy** by Amendment 0003 §4: `BaseWorldView` is a pinned logical read contract; eager complete in-memory materialization is allowed but not required |
| `implementation.md` §11.5 `Concurrency` | Describes optimistic concurrency + TimelineVersion CAS without explicitly naming the resulting Timeline-wide successful-commit serialization | **Materially augmented** by Amendment 0003 §5 |
| `implementation.md` §12.3 operational claimability summary | Assumes Capability handler availability as the only execution-target compatibility branch | **Already superseded** by Amendment 0001 §9 + Amendment 0002 §2, and **further augmented** by Amendment 0003 §3.2 |
| `implementation.md` §13.1 `Logical Work vs operational Work metadata` and §13.2 `World Binding enforcement` | Logical Work is described around a handler-only target and handler-specific execution compatibility | **Materially augmented** by Amendment 0003 §3.2: Work target/compatibility is target-specific while due/order/status/causal origin remain shared logical semantics |
| `implementation.md` §15.2 `Cognition stays in Agency by default` and §16 `Cognitive / Semantic Retrieval Boundary` | Defines the cognition tail but not durable Agent-wake orchestration/context production | **Materially augmented** by Amendment 0003 §3 |

### 1.2 Earlier accepted Amendment clauses affected

This Amendment does not invalidate the earlier liveness/scheduler rules, but it adds target-specific meaning where an Agency wake uses the same Scheduler chronology:

| Current clause | Effect of Amendment 0003 |
| --- | --- |
| Amendment 0001 §9 + Amendment 0002 §2 claim/admission contract | **Augmented** by Amendment 0003 §3.2: common due/lease/fence/budget rules remain; execution-target compatibility differs for Capability Work vs Agency Wake |
| Amendment 0001 §3.2 multi-worker rule | **Clarified, not changed** by Amendment 0003 §7: multi-worker correctness does not require one shared multi-threaded `Runtime` object; process/thread topology and Rust `Send`/`Sync` bounds remain implementation decisions |
| Amendment 0002 §3.2 minimum Chronology Budget unit | **Not replaced**. Amendment 0003 §6 records causal/derivation depth as an optional additive policy dimension, not a substitute for the mandatory total-completion safety counter |

If a baseline clause appears above, implementation tasks must cite this Amendment together with the frozen section.

---

## 2. Scope and non-goals

This Amendment deliberately does **not** redesign:

- TimelineVersion identity or the Timeline-level CAS linearization point;
- same-Timeline Scheduler logical-head ordering;
- the due-work quiescence barrier;
- the minimum Chronology Budget completion counter;
- World Runtime Binding scope;
- Event replay authority;
- the `Decision::Act(ActionInvocation) / NoAction` semantic result;
- Capability prohibition on generic Cognitive/Network/Provider handles;
- exact Rust async/object-safety syntax;
- exact database checkpoint/cache/index layout.

The goal is to make the existing architecture executable at the missing boundaries without creating a second Scheduler, a second World Time, or a second commit authority.

---

## 3. Agency wake and cognition execution closure

### 3.1 Agent wake reuses Scheduler-managed Durable Work chronology

An autonomous Agent wake is not a hidden timer callback, background thread, direct LLM job or external side channel.

In v0 it is a **Scheduler-managed durable execution obligation** and therefore inherits the existing Timeline chronology/liveness rules:

```text
Agency Wake scheduled for Timeline
        ↓
Durable logical obligation
        ↓
effective_due_world_time + logical_schedule_order
        ↓
logical head / semantic due-ness
        ↓
claim lease/fence
        ↓
Agent-wake Execution Session
        ↓
AgentWorldView assembly
        ↓
CognitiveExecutor
        ↓
Decision
        ↓
ActionInvocation / NoAction
        ↓
Runtime authority path
        ↓
Logical Commit completes current wake obligation
```

Therefore an Agency wake:

- is persistent/restartable before its result is determined;
- participates in the same `(effective_due_world_time, logical_schedule_order)` ordering as other Scheduler-managed obligations;
- blocks World Time while it is the semantically due logical head;
- cannot be skipped because cognition is slow, unavailable or in retry backoff;
- consumes the same minimum Chronology Budget unit when it successfully leaves `Pending` through its completion Logical Commit;
- is replayed/forked as logical Work state, while already-completed cognition is never re-run during historical replay.

This does **not** mean a Capability `WorkHandler` receives a CognitiveExecutor.

### 3.2 Durable Work has target-specific execution semantics

The existing scheduler chronology is shared, but v0 must distinguish at least two conceptual Work execution targets:

```text
Capability Work
└── Capability-owned WorkHandler

Agency Wake Work
└── Runtime-orchestrated Agency wake for an Entity acting in Agent role
```

Exact Rust representation (`WorkTarget` enum, tagged persisted target, separate typed record, etc.) is an implementation choice, but the semantic distinction is mandatory.

The common claim/admission conditions from Amendment 0001 §9 + Amendment 0002 §2 remain mandatory:

```text
semantically due
available_at <= PlatformTime.now
no conflicting valid lease/fence
chronology-budget/admission policy permits execution
```

Target-specific compatibility then applies:

```text
Capability Work
= owning semantic Capability is enabled by World Runtime Binding
  AND compatible WorkHandler implementation can be assembled

Agency Wake Work
= compatible Agency execution profile/context builder/cognitive executor can be assembled
  AND every Capability semantic domain read while assembling Agent context is permitted by the target World Runtime Binding
```

The eventual `Decision::Act(ActionInvocation)` still enters the normal Action routing path, so the Action owner must independently be installed/compatible and enabled by World Runtime Binding before any semantic mutation can commit.

Missing Agency execution software behaves like missing compatible execution software generally:

- execution does not begin merely because the logical Work is due;
- absence alone does not consume a technical execution attempt;
- the due head remains `Pending` and chronology-blocking;
- Runtime observability must identify that the blocked target is Agency execution rather than a Capability handler;
- recovery is compatible software restoration or the already-authorized Runtime logical terminalization path.

### 3.3 One root Agent-wake Execution Session

A claimed Agent wake starts one root Execution Session.

At Session start Runtime pins at least:

```text
target World / Timeline
input TimelineVersion / World Time
current Work identity + claim fence
World Runtime Binding
active Runtime Revision
compatible Capability implementation assembly
Agency execution profile / context-builder implementation
CognitiveExecutor implementation/provider/model configuration where applicable
Execution Policy / budgets
provenance origin = AgencyWake(agent Entity, Work identity)
```

The pinned Agency implementation/provider configuration must not silently change mid-wake.

The slow cognition phase is outside the short commit transaction. Runtime must never hold the Timeline write lock or commit transaction while waiting for model/provider/human/rule cognition.

### 3.4 AgentWorldView production authority

`AgentWorldView` remains subjective Agent knowledge/context and must never become an alias for authoritative `BaseWorldView`.

Ownership is split as follows:

```text
Capability semantics
= own observation/information/knowledge/memory/visibility World meaning

loom-agency contract
= owns AgentWorldView shape/composition contract,
  context budget contract and CognitiveExecutor SPI

loom-runtime
= owns pinned Session orchestration,
  World Binding enforcement,
  read-host mediation,
  provenance and commit authority

Application composition root
= wires concrete context/cognitive/provider implementations
```

Conceptual construction path:

```text
pinned Timeline read boundary
        ↓ Runtime-mediated, Binding-checked reads
Capability-owned observation / information / memory semantics
        ↓
Agency context builder / context selection
        ↓
AgentWorldView
        ↓
CognitiveExecutor
```

Agency code does **not** receive the unrestricted authoritative `BaseWorldView` object as its cognition input. Runtime may internally use the same pinned read substrate to answer context-builder queries, but only the filtered/subjective `AgentWorldView` crosses into cognition.

A context builder may request only semantics authorized for the target World. Registry presence or global indexes never grant Agent visibility.

### 3.5 Cognition result and atomic Work completion

Cognition produces only:

```text
Decision::NoAction
Decision::Act(ActionInvocation)
```

For `NoAction`:

```text
Decision::NoAction
        ↓
Runtime-owned Work-only Logical Commit
        ↓
current Agency Wake Work -> Completed
```

For `Act(ActionInvocation)`:

```text
Decision::Act(ActionInvocation)
        ↓
normal Runtime Action routing / owner / Binding / schema checks
        ↓
Capability Resolution
        ↓
Runtime validation
        ↓
one commit attempt containing:
  Event/Effects/Work mutations from the Action
  + completion of current Agency Wake Work
  + chronology-budget consumption
```

The Agent does not first commit a durable `Decision` and later execute it as a second semantic truth step. Decision is execution/provenance data until the Action commit succeeds.

If the Action is semantically rejected, Runtime policy may complete the wake as a determined no-world-change outcome; rejection does not automatically create a World Event.

### 3.6 CAS conflict, lease expiry and duplicate cognition

Because cognition can be slow, another worker/process may race, a lease may expire, or an unrelated root input may advance the TimelineVersion before the Agent action commits.

Correctness rules:

- the commit must validate the current Work fence/lease and expected TimelineVersion;
- a stale/fenced-out cognition result can never commit World mutation or complete the Work;
- losing workers discard their computed result and reload/retry according to Runtime policy;
- the same logical wake may therefore execute cognition more than once under at-least-once platform failure, but at most one result may become the successful logical outcome;
- provider calls, model refs, inputs/outputs/hashes where retained, and losing/winning Session evidence belong to Execution Provenance, not World History;
- retry after a true cognition/provider failure follows bounded Runtime FailurePolicy;
- software absence before execution starts does not consume a technical attempt.

If a re-resolution/re-cognition happens after Timeline conflict, entropy/cognition reuse versus resample must be explicit Runtime policy and provenance. Hidden accidental reuse/resampling is forbidden.

### 3.7 Scheduling an Agency wake

Scheduling the future execution obligation is Runtime authority over Timeline Logical State, not direct World mutation.

v0 may expose a focused Runtime/Agency control through `loom-api` or let Runtime/Application Agency policy request it, but the request must converge on a Runtime-owned Logical Commit that creates the Agency Wake Work with deterministic schedule/order.

The exact public DTO/service name is an implementation decision. The following are forbidden:

```text
Cognitive provider directly INSERTs Work
Application writes scheduler tables
Capability receives a raw scheduler/DB handle
Agent secretly sleeps until wall clock time and calls Runtime
PlatformClock passage implicitly creates or advances an Agent wake
```

Long-lived goals, desires, personality, memory and world-semantic Agent conditions remain Capability-owned World State where appropriate. Scheduling metadata itself is Timeline Logical State.

### 3.8 Replay and fork

Historical replay never re-runs CognitiveExecutor.

Replay applies the already committed Event/Effects and logical Work transitions. Execution Provenance may explain which cognition produced a committed action but is not used to recompute history.

Fork behavior follows the normal Durable Work rule:

- a `Pending` inherited Agency Wake is cloned as branch-local future Work with preserved effective due time and relative logical order;
- operational lease/retry state resets;
- completed cognition is not re-executed merely because the branch reconstructs history;
- branch-local future wake/cognition may diverge after the fork.

---

## 4. Pinned World read boundary without mandatory full-world materialization

### 4.1 `BaseWorldView` is a consistency contract, not a storage shape

The authoritative meaning of a pinned `BaseWorldView` is:

> Every World fact returned to one semantic execution belongs to the same pinned Timeline logical snapshot position.

It does **not** mean:

> Runtime must eagerly load every Entity, Relationship, Facet and Event in the Timeline into a fresh private in-memory structure before every Resolution.

Eager complete materialization remains a valid simple implementation, especially for tests/small Worlds, but it is no longer a mandatory interpretation of `runtime-contracts.md` §16.5.

Capability/Agency code still must not receive SQL, a repository, transaction, `PgPool`, platform clock or mutable persistence handle.

### 4.2 Allowed implementation families

A Runtime may satisfy the pinned read contract using one or a combination of:

```text
A. eager immutable snapshot
B. shared revision-keyed immutable cache / persistent data structure
C. bounded prefetch of an execution working set
D. version-fenced lazy Runtime reads
E. synchronous view + explicit miss/refill/restart protocol
```

The architecture does not freeze which family re-planning selects first.

For any strategy, a Capability-observed result must never be a silent mix of Timeline revisions.

### 4.3 Version-fenced lazy reads

If Runtime performs persistence I/O lazily, each returned read must prove it belongs to the Session's expected TimelineVersion.

One valid pattern is a short read-only database snapshot per lazy batch:

```text
BEGIN READ ONLY / consistent snapshot
read TimelineVersion
require == pinned version
perform requested World read/query
return result from that same DB snapshot
COMMIT/ROLLBACK read transaction
```

A later lazy read that observes a different TimelineVersion must fail the current semantic execution before returning mixed-revision data and force Runtime reload/re-resolution.

Equivalent revision-addressed storage/cache mechanisms are allowed.

The important contract is **pinned consistency**, not one specific PostgreSQL trick.

### 4.4 No hidden blocking persistence inside Capability code

Removing mandatory eager full-world loading does not permit a synchronous Capability trait to secretly perform arbitrary blocking SQL on an async executor thread.

Re-planning must choose an explicit Rust execution strategy, for example:

- keep synchronous Capability view APIs over a prepared/cache-backed view and use miss/refill/restart;
- adopt an architecture-compatible async host/view SPI;
- use another mechanism that preserves object/dependency boundaries and does not expose persistence authority.

Exact `async_trait`/RPITIT/boxed-Future/object-safety syntax is not frozen here.

### 4.5 ReadSet remains observed

`ReadSet is observed, not predicted` remains unchanged.

A scalable read path should record the actual point/predicate/range/negative/semantic reads that were answered. It must not require every Capability to predeclare a complete future working set merely to avoid full-world loading.

### 4.6 Large-world readiness

The architecture no longer equates correctness with O(total World state) loading per execution.

However, Loom must not claim large-World readiness merely because the semantic contracts allow it. Re-planning/benchmark evidence must distinguish:

```text
semantic scalability allowed by architecture
!=
current implementation proven scalable
```

The current eager snapshot path may remain an intermediate implementation, but a production large-World milestone must measure read amplification, snapshot/cache behavior and CAS conflict rates.

---

## 5. v0 Timeline concurrency statement

The following is an explicit consequence of the already-frozen TimelineVersion/CAS model:

> **Successful Timeline logical commits are serialized at Timeline scope in v0.**

This is more precise than saying “the whole Timeline has one physical writer.”

Multiple executions may perform pre-commit work concurrently where their admission rules permit, but two successful commits based on the same old TimelineVersion cannot both win.

Therefore:

```text
External/root Actions
= may Resolve concurrently
  -> compete at Timeline CAS
  -> losers reload/revalidate/re-resolve

Scheduler-managed Durable Work
= logical-head admission additionally prevents later same-Timeline Work
  from starting semantic execution before the due head is resolved

Different Timelines
= independent chronology / CAS domains and may progress concurrently
```

v0 intentionally accepts coarse-grained same-Timeline write conflicts in exchange for a simple deterministic linearization point.

Fine-grained ReadSet-based commit validation/concurrency is **deferred**. If adopted later, it must be an Architecture Amendment because it changes what `TimelineVersion` conflict means and can affect deterministic ordering, replay expectations and commit authority.

No v0 claim should imply that one Timeline is designed for arbitrary same-instant hundred-thousand-Agent write throughput without benchmark/architecture evolution evidence.

---

## 6. Chronology Budget interpretation

The v0 minimum total-completion counter from Amendment 0002 §3.2 remains mandatory.

It is a safety/liveness budget, not a perfect classifier of “buggy recursion” versus “legitimate fan-out.” A legitimate large fan-out may exceed a configured safety budget and require a larger policy allowance or operator intervention.

Causal/derivation depth is a useful **additional** dimension and may be introduced by Runtime policy, for example from `origin_work_id` / causal ancestry, but it does not replace total work/compute protection.

Conceptually future policy may combine:

```text
total same-WorldInstant completions
reaction/derivation depth
total schedules
compute/session cost
cognition/token/provider cost
```

Any added reconstructable dimension must declare its authority/persistence semantics before enforcement.

---

## 7. Worker topology and Rust `Send` / `Sync`

Amendment 0001's multi-worker rule means Loom correctness must not assume exactly one physical worker/process drives a Timeline.

It does **not** require all workers to share one multi-threaded in-process `Runtime` object.

Both can satisfy the architecture, for example:

```text
multi-thread/process-safe shared Runtime
        OR
multiple single-thread Runtime instances/processes
        ↓
shared authoritative persistence
        ↓
head-aware claim + lease/fence + TimelineVersion CAS
```

Therefore current missing `Send`/`Sync` bounds are not by themselves an architecture contradiction.

Before `loom-server` / production worker hosting is considered complete, re-planning must explicitly choose the executor/topology and audit all relevant boundaries together:

- `loom-api` futures/service traits;
- Runtime persistence futures/ports;
- Capability registry and Resolver/WorkHandler trait objects;
- Agency context/cognitive SPI;
- concrete Storage adapters;
- worker ownership/lifecycle.

Adding `Send` to two Future aliases alone is not sufficient evidence of a coherent worker model.

---

## 8. Historical replay/fork checkpointing

No checkpoint is required to define correct replay/fork semantics.

A checkpoint/snapshot accelerator is a derived projection such as:

```text
checkpoint @ TimelineVersion V
        +
replay authoritative Events/logical commits from V -> target
```

It does not replace Event Ledger / Logical Commit Journal authority.

Historical replay/fork checkpointing is deferred for v0 unless measured history length makes the O(history) reconstruction path unacceptable for a required milestone. If introduced, checkpoint corruption/deletion must never change authoritative history semantics.

---

## 9. Re-planning gate after Amendment 0003

With this Amendment accepted:

- autonomous Agent wake/cognition has one durable Runtime execution path;
- AgentWorldView has an explicit producer/orchestration authority split;
- slow cognition is outside commit transactions but still protected by claim fence + Timeline CAS;
- `BaseWorldView` no longer mandates eager full-world materialization;
- v0 Timeline-wide commit serialization is explicit;
- fine-grained concurrency, checkpoint acceleration and worker executor topology are visible deferred/re-planning items;
- Chronology Budget keeps its total-completion safety counter, with depth only as an optional additive dimension.

After the Architecture Index, glossary and execution guardrails are updated to reference this Amendment, architecture-blocking open questions are again **none** and V0 implementation re-planning may begin.
