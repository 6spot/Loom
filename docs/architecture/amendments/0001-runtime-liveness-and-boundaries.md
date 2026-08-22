# Architecture Amendment 0001 — Runtime Liveness and Boundary Closure

> Status: **ACCEPTED for Loom v0 architecture baseline.**
>
> Base baseline: `a2238f05e649dc30ce21da1e1cb321bc2784e895`.
>
> This Amendment exists because the frozen scheduler chronology contract exposed several missing exit/ownership paths. It does **not** change Loom's five semantic layers, Cargo DAG, World Runtime Binding model, explicit World Time model, Logical Commit authority or Execution Session model.
>
> Where this Amendment conflicts with the frozen baseline, this Amendment wins for the clauses explicitly named below.

---

## 1. Runtime Work Failure Policy

The frozen baseline correctly distinguishes semantic due-ness from operational claimability, but a due head Work cannot be allowed to retry forever without a defined terminal path.

### 1.1 Ownership

`FailurePolicy` is Runtime policy, not Capability semantics and not World State.

A Capability WorkHandler may succeed, reject according to its semantic contract, or fail through the technical error channel. It does not decide lease/backoff/max-attempt policy and cannot mark itself `Dead` directly.

### 1.2 Technical failure outcomes

After a technical execution failure, Runtime Failure Policy decides one of:

```text
Retry
├── same WorkId
├── same effective_due_world_time
├── same logical_schedule_order
├── increment operational attempt metadata
└── choose new available_at using Platform Time

Terminalize
└── Runtime-owned Logical Commit: Pending -> Dead
```

Automatic technical retry **must be bounded** in v0. The exact numeric attempt limit/backoff curve is configuration, not architecture, but the policy may not mean "retry forever with no terminal/operator exit".

### 1.3 What does not count as an attempt

A Work that cannot start because the active Runtime Revision lacks a compatible handler implementation has not executed and does not consume a technical execution attempt merely because software is unavailable.

It remains `Pending`, semantically due if its World Time condition is met, and continues to block later same-Timeline Scheduler Work until:

- compatible software becomes available; or
- an authorized Runtime Control operation logically `Cancelled`/terminalizes that Work.

### 1.4 Terminal state authority

`Dead` and `Cancelled` are Timeline Logical State.

They require Runtime-owned Logical Commit + TimelineVersion advance. Deleting a row, writing only `last_error`, expiring a lease or exhausting a platform counter is not sufficient.

A world that needs the failure/cancellation to become semantic World Truth must still express that meaning through an explicit Capability Event.

### 1.5 Operator/runtime control

`loom-api` Runtime/Timeline Control must be able to express an authorized operation that causes a blocked Pending Work to enter an allowed terminal logical state.

The public DTO/authorization details are implementation/API design, but the authority path is fixed:

```text
Operator / Runtime Policy
        ↓
loom-api Admin / Runtime Control
        ↓
Runtime validation + expected TimelineVersion
        ↓
Logical Commit
        ↓
Pending -> Cancelled / Dead
```

A previously `Dead` Work is not resurrected in place. If an operator/domain wants another attempt after terminalization, create a **new Work** with provenance/origin reference to the old Work.

---

## 2. Same-World-Time Chronology Budget

The head-of-line + quiescence rules intentionally prevent World Time from skipping due Work. They therefore also require a guard against infinite chains of new Immediate Work at the same WorldInstant.

### 2.1 Cross-commit budget

Runtime must apply a **Chronology Budget** across Scheduler executions/Logical Commits at one Timeline WorldInstant.

The budget is not limited to a single Execution Session or subresolution call stack. It must detect chains such as:

```text
W1 @ T20
→ Event
→ Reaction
→ Immediate W2 @ T20
→ Event
→ Reaction
→ Immediate W3 @ T20
→ ...
```

### 2.2 Reconstructability

Budget consumption must be reconstructable from persistent logical/provenance history or equivalent durable counters tied to the Timeline/WorldInstant. A process restart must not reset the chain to zero.

Fork at a WorldInstant inherits the already-determined ancestry at that instant; branch-local future consumption then diverges normally.

### 2.3 Budget exhaustion behavior

When the chronology budget is exhausted:

```text
STOP automatic Scheduler progression at current World Time
DO NOT AdvanceWorldTime while semantically due Pending Work remains
surface ChronologyBudgetExceeded through Runtime observability/control
require policy/operator/domain correction before further automatic progression
```

Budget exhaustion is **not** permission to violate the due-work quiescence barrier.

Exact numeric limits and optional dimensions (work count, reaction-derived count, compute/session count) are Runtime policy configuration.

### 2.4 Why this is not a World Event

The budget is a Runtime liveness/safety control. Reaching it does not automatically create semantic World Truth. If a domain needs an in-world consequence, that consequence must still be produced through normal Capability semantics.

---

## 3. Scheduler Driver Ownership and Concurrency

### 3.1 Logical owner

`loom-runtime` owns the Scheduler / Timeline Driver state machine and all decisions about:

- which Pending Work is the logical head;
- semantic due-ness;
- operational claimability;
- chronology-budget admission;
- whether a Timeline is scheduler-quiescent;
- whether a requested World Time advance is legal.

`loom-storage` implements Runtime-owned persistence/claim/fencing ports. Storage never defines the chronology.

The composition root (`loom-server` or another Application) hosts/starts Runtime scheduler workers and provides policy/configuration; it does not choose the next Work semantically.

### 3.2 No single-process assumption

v0 does **not** require exactly one physical worker/driver per Timeline.

Multiple Runtime workers may race to drive the same Timeline. Correctness comes from one logical authority enforced by:

```text
head-aware claim lease/fence
+
TimelineVersion CAS
+
transactional re-check of quiescence / head conditions
```

Losing workers must fail/reload rather than produce a second logical success.

> **Single logical authority does not imply single physical process.**

### 3.3 Time advancement races

Two drivers may concurrently conclude that a Timeline appears quiescent and request `AdvanceWorldTime`. The successful logical commit must re-check expected TimelineVersion/current World Time/quiescence. At most one succeeds; the other reloads.

---

## 4. `FOR UPDATE SKIP LOCKED` Boundary

PostgreSQL `SKIP LOCKED` is an implementation tool, not a chronology rule.

It may be used to distribute work **across independent Timeline heads**. For example, if Timeline A's head is already leased/locked, a worker may choose Timeline B's eligible head.

It must never be used to skip the logical head **within the same Timeline** and claim a successor.

Forbidden behavior:

```text
Timeline A:
W1 = due logical head, locked/backoff/unclaimable
W2 = later Work

SQL skips W1 and claims W2   ← forbidden
```

The persistence API/query must preserve Runtime's sequence:

```text
select logical head
        ↓
is that head semantically due?
        ↓
is that same head operationally claimable?
        ↓
claim that same head or claim nothing for this Timeline
```

---

## 5. Event Occurrence-Time Ownership

The frozen baseline says v0 Events occur at the Execution Session's pinned World Time. Therefore Capability proposals do not need authority to choose that time.

### 5.1 Superseded baseline wording

This Amendment supersedes baseline examples that require Capability code to supply an authoritative `ProposedEvent.occurred_at` equal to `ctx.world_time()`.

### 5.2 v0 rule

Conceptually:

```text
Capability ProposedEvent
    event semantics / payload / refs / frozen effects proposal
        ↓
Runtime validation using pinned BaseWorldView
        ↓
Runtime stamps authoritative occurred_at = pinned World Time
        ↓
Committed Event
```

The exact Rust proposal type should therefore omit authoritative `occurred_at` in v0, or otherwise make it impossible for Capability to choose a different value. Runtime owns the stamp.

Source-system timestamps, legal effective dates, historical observation dates or report times remain explicit domain payload/scope semantics and do not advance World Time.

---

## 6. Ingress Contract Closure

Ingress is no longer an unspecified parallel execution model.

### 6.1 Meaning

Ingress is the reliable external-input envelope/boundary around a normal semantic attempt.

A v0 Ingress envelope conceptually contains:

```text
IngressId / idempotency key
source / provenance
Target World / Timeline
source/platform time metadata
authorization context
ActionInvocation
```

### 6.2 Public/API path

`loom-api` includes an `Ingress` capability/service domain for accepted external input.

Canonical flow:

```text
External system
      ↓
Boundary / Application adapter
      ↓
Ingress envelope
      ↓
loom-api Ingress service
      ↓
Runtime dedupe / authorization / provenance
      ↓
ExecutionOrigin::Ingress
      ↓
normal Action routing / World Binding / Execution Session
      ↓
Resolution -> validation -> Logical Commit
```

Ingress acceptance/deduplication does not itself make the input payload World Truth.

### 6.3 No generic IngressHandler in Capability

v0 does not add a second semantic handler hierarchy for ingress. A Capability interprets an external fact/command through an explicit Action it owns (for example `weather.observe_external_report` if such semantics exist).

This keeps one semantic authority path instead of Action vs IngressHandler duplication.

### 6.4 Time

Ingress source/platform time metadata never implicitly advances World Time. Any real-world mirror mapping still goes through explicit authorized `AdvanceWorldTime` policy/control.

---

## 7. World Template Technical Placement

World Template semantics were already defined; this Amendment fixes their technical ownership without adding a new crate.

### 7.1 `loom-api`

Owns stable public consumption contracts such as:

```text
WorldTemplateDescriptor
TemplateId/revision descriptor values as required
CreateWorldFromTemplateRequest / result
Template discovery/read contracts where exposed
```

Public descriptor types are not Runtime authority tokens.

### 7.2 `loom-runtime`

Owns:

```text
Template validation
Capability dependency/compatibility closure
active Runtime Revision compatibility resolution
ValidatedWorldBirthPlan authority value
bootstrap Execution Session orchestration
atomic World + initial Timeline + Binding + bootstrap commit orchestration
Runtime-owned Template/Binding persistence ports where persistence is needed
```

`ValidatedWorldBirthPlan` is analogous to other Runtime authority values: consumers may request birth, but only Runtime can create the validated authority to commit it.

### 7.3 `loom-storage`

Implements Runtime-owned Template/Birth/Binding persistence ports. Storage does not validate semantic compatibility by itself.

### 7.4 Application / composition root

May provide/register/select Template definitions/configuration and installed implementations, but cannot bypass Runtime birth validation or directly initialize semantic Entity/Facet state through Storage.

No `loom-template` crate is required for v0.

---

## 8. Terminology Reconciliation

### 8.1 Intent

`Intent` remains a useful conceptual/Agency term meaning what an Actor wants to attempt.

v0 has **no generic Runtime `Intent` protocol type**. Runtime execution contracts use `Decision`, `ActionInvocation`, `Resolution`, etc.

Any baseline wording such as "Core defines the Intent protocol" is superseded by this distinction.

### 8.2 Trigger and Reaction

`Trigger` is a conceptual umbrella, not a third Runtime primitive.

```text
Temporal Trigger
= Durable Work WorkSchedule::At(WorldInstant)

Event Trigger
= Reaction registration
  -> matching committed Event
  -> schedules Immediate Durable Work
```

`AdvanceWorldTime` is not a Trigger; it is Runtime Timeline logical authority.

### 8.3 Actor and Agent

`Entity` is the Core identity primitive.

`Actor` means an Entity in an action/event role. `Agent` means an Actor/Entity participating in Agency cognition/decision contracts.

v0 does not require `Actor` or `Agent` as persisted `loom-core` subtype/tag primitives. Domain/Agency state can mark/configure agent participation through appropriate higher-level contracts/state without changing Entity identity.

---

## 9. Claimability Checklist Canonicalization

For scheduler purposes, the canonical distinction is:

```text
Semantic due-ness
= Pending
  AND effective_due_world_time <= Timeline.world_time

Operational claimability
= semantically due
  AND available_at <= PlatformTime.now
  AND no conflicting valid lease/fence
  AND owning semantic Capability is enabled by World Runtime Binding
  AND a compatible handler implementation can be assembled for execution
  AND chronology-budget/admission policy permits execution
```

No summary in `implementation.md`, `AGENTS.md` or elsewhere may shorten this list in a way that changes semantics. Such documents should reference this contract instead of defining their own competing list.

---

## 10. Non-goals and deferred choices

This Amendment intentionally does not freeze:

- numeric retry attempt count;
- backoff algorithm;
- numeric chronology-budget limits;
- scheduler polling frequency/worker count;
- exact Rust names for the Runtime scheduler service;
- exact Admin authorization/DTO shape;
- PostgreSQL query/index shape beyond the logical `SKIP LOCKED` restriction;
- dynamic Capability hot-plug/migration.

Those are implementation/policy decisions unless they later change semantic authority/replay/fork/ordering behavior.

---

## 11. Amendment acceptance summary

After this Amendment, the scheduler liveness loop is closed:

```text
due head
  ↓
claimable? ── no ──> remains barrier
  │                    │
 yes                   ├─ implementation restored
  │                    ├─ retry becomes claimable
 execute                └─ authorized logical terminalization
  ↓
technical failure
  ↓
bounded FailurePolicy
  ├─ Retry same Work
  └─ Logical Commit -> Dead

same-time automatic chain
  ↓
Chronology Budget
  ├─ within budget -> continue deterministic head order
  └─ exceeded -> halt automatic progression at same World Time
```

And external/runtime boundaries are closed without adding new semantic layers or Cargo cycles.
