# Architecture Amendment 0005 — Automatic Bounded Timeline Discovery

> Status: **ACCEPTED for Loom v0 architecture baseline.**
>
> Depends on: `0001-runtime-liveness-and-boundaries.md`,
> `0002-supersession-and-authority-linkage.md`,
> `0003-agency-execution-and-pinned-read-boundary.md`, and
> `0004-derived-resource-public-read-boundary.md`.
>
> This Amendment freezes the smallest architecture change needed for the
> official server to discover Scheduler Timeline targets after startup. It
> changes application target enumeration, not World or Timeline semantic
> authority. The current deployment-configured target implementation remains
> unchanged until a separately scoped implementation task applies this
> contract.

## 1. Exact affected-clause index

Frozen baseline documents remain historical snapshots. This Amendment changes
their current interpretation through explicit linkage rather than silently
rewriting the old text.

| Baseline location | Baseline meaning | Current authority |
| --- | --- | --- |
| `world-runtime.md` §8.1 `Semantic due-ness vs operational claimability` | Defines semantic due-ness and operational claimability for a Work, but does not define a separate discovery predicate for selecting Timeline targets | **Materially augmented** by Amendment 0005 §3.1–§3.2: discovery is an operational observation; it must not reuse due/claimability filters to hide future or temporarily unclaimable Pending Work |
| `world-runtime.md` §8.7 `Time advancement policy` | Allows Application/Runtime policies to request explicit World-Time advancement, without fixing how an application finds Timelines that may need a drive | **Materially augmented** by Amendment 0005 §3.1–§3.5: the official server may discover targets dynamically, while only Runtime may decide and commit a legal advancement |
| `world-runtime.md` §8.8 `Auto-advance safety` | Freezes due-work, head, restart and same-Timeline ordering safety for automatic progression | **Clarified, not relaxed** by Amendment 0005 §3.2–§3.4: discovery may surface future or blocked targets for Runtime inspection, but cannot bypass any safety rule |
| `world-runtime.md` §8.9 `Scope of this ordering law` | Defines Scheduler Work ordering and does not create a global total-order input queue | **Clarified** by Amendment 0005 §3.1–§3.4: target enumeration is not a queue, logical ordering mechanism or second authority path |
| `runtime-contracts.md` §14.10–§14.11 `Semantic due-ness` / `Operational claimability` | Defines the Work predicates used by Runtime admission | **Augmented** by Amendment 0005 §3.2–§3.4: these predicates remain Runtime decisions; discovery does not claim, reserve or discard a target based on them |
| `runtime-contracts.md` §14.16–§14.17 `World Time advancement` / `Time advancement policy` | Requires explicit Runtime-owned advancement and permits Application/Runtime policy choices | **Augmented** by Amendment 0005 §3.1–§3.2 and §3.5: a discovered future-Work Timeline remains eligible for Runtime to perform a legal explicit advancement |
| `implementation.md` §4.2 `Composition root` | Places worker hosting and concrete assembly in the Application while keeping next-Work semantics in Runtime and persisted logical state | **Materially augmented** by Amendment 0005 §3.5: the Application may host bounded target discovery, but still cannot choose a logical head or semantic transition |
| `implementation.md` §6.7 `Application` and §12.6 `Time policy vs authority` | Allows Application/Runtime policy/configuration around time progression | **Augmented** by Amendment 0005 §3.2–§3.5: discovery policy is bounded operational plumbing; it cannot replace explicit Runtime authority or require deployment target IDs |
| `implementation.md` §13.3 `Deterministic claim semantics` | Requires Runtime semantics to determine the logical head before a persistence adapter claims it | **Clarified** by Amendment 0005 §3.1–§3.4: discovery is strictly before that Runtime claim/admission boundary and cannot use a discovery reservation or a same-Timeline skip |
| `governance.md` §4.3 `Applications` and §10 `Composition Root` | Makes Applications composition roots that wire implementations while World Binding and execution authority remain in Runtime | **Materially augmented** by Amendment 0005 §3.5: the official server may wire a dynamic discovery loop without gaining semantic authority |

If a baseline clause appears above, implementation tasks must cite this
Amendment together with the frozen section.

## 2. Problem and design constraint

The current application path can be given one deployment-configured
`(WorldId, TimelineId)` target. That is an implementation convenience, not a
semantic requirement, but it leaves the official server unable to notice
newly-created or independently-forked Timelines without deployment changes or
a restart/reload.

The minimal repair is to separate two operations that are currently easy to
conflate:

```text
operational target discovery
        ↓
Runtime::drive_timeline(target, ...)
        ↓
Runtime semantic head/admission/commit authority
```

Target discovery is **operational/platform discovery, not World Truth**. It may
identify a Timeline to inspect. It does not become a durable World fact, a
Timeline logical transition, a Work claim, or a public semantic catalog.

## 3. Automatic bounded discovery contract

### 3.1 Discovery is an advisory Runtime entrypoint

The official server may enumerate Scheduler targets dynamically after startup;
it does not require deployment-provided target IDs to notice an existing
World/Timeline or one created after startup. A discovery result is an advisory
`TimelineTarget` observation and may be stale by the time the application
passes it to Runtime.

Discovery may **not**:

```text
choose or skip the Timeline's logical head
claim or reserve Work
advance World Time
commit Events, Effects, Work status or any other semantic state
decide World Binding enablement
```

`Runtime::drive_timeline(target, ...)` remains the semantic authority boundary.
For every discovered target, Runtime reloads the authoritative Timeline state,
selects the persistent logical head, applies semantic due-ness and operational
claimability, and performs any legal Work or World-Time Logical Commit. A
discovery scan can therefore be incomplete or stale without becoming a second
authority path.

### 3.2 Candidate visibility includes future and blocked logical Work

The discovery candidate set must retain any existing Timeline with logical
`Pending` Work, including a Timeline whose Pending Work is:

```text
future relative to the current Timeline World Time
temporarily unavailable because of Platform-time backoff or a valid lease
blocked by missing compatible execution software
otherwise not currently operationally claimable
```

In particular, **Timelines with future-World-Time Pending Work must remain
discoverable**. Runtime may need to inspect such a target and, only after its
own quiescence and policy checks, perform a legal explicit World-Time
advancement to the next due Work. Filtering discovery by
`effective_due_world_time <= world_time`, `available_at <= PlatformTime.now`,
handler availability, lease state or chronology budget would hide a logical
future and is forbidden.

Discovery does not decide whether a target is due, claimable, quiescent or
advanceable. Those remain Runtime decisions under the existing
World-Time/Work contracts.

### 3.3 Bounded scans must be fair without defining a storage design

Each discovery round must be bounded in the amount of target metadata it
observes and in the number of `Runtime::drive_timeline` calls it initiates.
The bound is an application/platform liveness limit; it is not a semantic
priority and must not alter same-Timeline logical order.

Across repeated rounds, a Timeline that remains in the discovery candidate set
must not be permanently starved merely because earlier targets remain present,
or because an earlier target is repeatedly leased, retrying, unavailable or
otherwise unable to make progress. The bounded scan must advance an
enumeration frontier or use an equivalent fairness rule so later stable
Timeline targets are eventually surfaced. A target that leaves the candidate
set may naturally disappear before its turn; re-entry is handled by the same
bounded policy.

The Amendment intentionally does **not** freeze a SQL query, index, cursor
encoding, page size, poll cadence, in-memory queue, or persistence schema for
this fairness requirement. Any implementation is correct only if it preserves
bounded work and the non-starvation property.

### 3.4 Multiple server processes and duplicate discovery

Multiple official server processes may discover the same Timeline. Duplicate
discovery is an efficiency concern, not a second authority path and not a
reason to add a discovery-level reservation protocol.

Existing correctness contracts remain authoritative:

```text
head-aware Work lease/fence
+ TimelineVersion CAS
+ transactional Runtime re-checks
```

A duplicate or stale discovery may result in redundant `drive_timeline` calls,
but it cannot permit two semantic winners, skip a logical head, advance World
Time outside Runtime, or commit duplicate semantic state. The Amendment does
not introduce leader election, a global Scheduler owner, or a new
multi-process topology contract.

### 3.5 Application topology and migration boundary

The Application composition root owns the lifecycle of the bounded discovery
loop: startup/reload integration, poll budget, shutdown handling and the
operational handling of stale/duplicate observations. It wires the existing
Runtime and persistence ports; it does not interpret logical Work or mutate
Timeline state.

The follow-up implementation may replace the requirement for
`LOOM_SCHEDULER_WORLD_ID` and `LOOM_SCHEDULER_TIMELINE_ID` with automatic
discovery. This Amendment does not edit those existing configuration files,
remove their current parser, add replacement variables, or claim that the
current server already performs discovery. No deployment target IDs are part
of the resulting semantic contract, and no new configuration variable is
authorized by this Amendment.

Newly created or forked Timelines become discoverable during normal server
operation without a deployment edit or restart. Whether a process chooses to
drive an observed target immediately remains bounded application scheduling;
the semantic result always returns to `Runtime::drive_timeline`.

## 4. Preserved authority and explicit non-goals

This Amendment does not change:

- persistent `(effective_due_world_time, logical_schedule_order)` ordering;
- the same-Timeline logical-head and due-work quiescence barriers;
- Chronology Budget semantics or FailurePolicy;
- World Runtime Binding, Event/Effect or replay/fork authority;
- `Runtime::drive_timeline` or Runtime-owned Logical Commit authority;
- the existing lease/fence/CAS multi-process correctness model;
- the current single-thread-per-process implementation choice;
- any public API, schema, SQL migration, or storage table;
- `LISTEN/NOTIFY`, discovery-level `SKIP LOCKED` reservation, or a queue service;
- bootstrap/default World behavior, new configuration variables, or deferred
  multi-process topology decisions.

Discovery must never be used to justify any of the following shortcuts:

```text
SELECT a later same-Timeline Work because the head is unavailable
advance Timeline.world_time in the Application
write a discovery record into World History or Timeline Logical State
let a global catalog decide per-World enablement
replace Runtime::drive_timeline with an Application-side executor
```

## 5. Re-planning consequence and stop condition

After this Amendment, the next implementation task may add bounded automatic
Timeline discovery in the official server while preserving the existing
Runtime call and authority boundaries. It must update operational guides and
tests only as part of that implementation scope; this architecture task does
not pre-claim those changes.

If an implementation cannot discover targets without moving logical-head
selection, Work claiming, World-Time advancement or semantic commit authority
out of Runtime, it must stop and record that conflict rather than embedding a
larger Scheduler redesign in this Amendment.

## 6. Acceptance

This Amendment is satisfied only when the contract above is used for
re-planning and review:

- exact frozen Scheduler/application clauses are named in this document and
  the Architecture Index;
- discovery is explicitly operational/platform discovery, not World Truth;
- `Runtime::drive_timeline(target, ...)` remains the semantic authority
  boundary and discovery cannot choose/skip heads, claim Work, advance World
  Time or commit semantic state;
- bounded discovery cannot permanently starve later stable Timeline targets,
  without freezing an unnecessary SQL/index design;
- future-World-Time Pending Work remains discoverable;
- duplicate discovery across server processes is treated as an efficiency
  concern under the existing lease/fence/CAS rules;
- the official server may discover Timelines after startup without deployment
  target IDs, with no new public API or configuration variable introduced by
  this Amendment;
- no implementation code, schema/SQL, `LISTEN/NOTIFY`, discovery reservation,
  bootstrap/default World or deferred multi-process topology is smuggled into
  the architecture change.
