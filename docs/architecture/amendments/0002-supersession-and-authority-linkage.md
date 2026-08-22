# Architecture Amendment 0002 — Supersession and Authority Linkage

> Status: **ACCEPTED for Loom v0 architecture baseline.**
>
> Depends on: `0001-runtime-liveness-and-boundaries.md`.
>
> This Amendment does not redesign Loom Runtime semantics. It closes documentation-linkage and authority-placement gaps discovered after Amendment 0001, and makes supersession mechanically auditable before v0 re-planning.

---

## 1. Exact supersession index

Frozen baseline documents remain historical snapshots. We do **not** silently rewrite their old clauses to pretend the original freeze said something it did not.

Instead, any accepted Amendment that changes a frozen clause must name the exact affected location. Readers and planning agents must consult the Architecture Index supersession table before treating a baseline clause as current.

The following baseline clauses are superseded, materially augmented, or have their specification status changed by Amendment 0001 / this Amendment:

| Baseline location | Baseline meaning | Current authority |
| --- | --- | --- |
| `core.md` §2.1 `World Primitives` (`Actor`, `Agent`) | Actor/Agent appear as Core primitive categories | **Superseded** by Amendment 0001 §8.3: Entity is the Core identity primitive; Actor/Agent are semantic/Agency roles, not required persisted Core subtypes |
| `core.md` §4.3 `Entity / Actor / Agent` | Persisted-looking Entity → Actor → Agent hierarchy | **Superseded** by Amendment 0001 §8.3 |
| `core.md` §7.3 `Scheduler / Trigger` | Temporal Trigger / Event Trigger can be read as separate Runtime primitives | **Superseded/clarified** by Amendment 0001 §8.2: Temporal Trigger = `WorkSchedule::At`; Event Trigger = Reaction → Immediate Work; `AdvanceWorldTime` is not a Trigger |
| `core.md` §8.4 `Decision and cognition` sentence “Core defines Decision / Intent protocol” | Generic Runtime Intent protocol implied | **Superseded** by Amendment 0001 §8.1: Intent is conceptual/Agency terminology; v0 has no generic Runtime `Intent` protocol type |
| `core.md` §9.2 `Runtime Authority` budget reference | Reaction execution is said to be controlled by work/reaction/compute budgets, but the durable same-World-Time accounting semantics are not defined | **Materially augmented** by Amendment 0001 §2 + Amendment 0002 §3: same-World-Time Chronology Budget is reconstructable Timeline Logical State with a defined minimum consumption unit |
| `world-runtime.md` §6.4 Event-time example | Capability proposal supplies authoritative `ProposedEvent.occurred_at` | **Superseded** by Amendment 0001 §5: Runtime stamps authoritative occurrence time from the pinned World Time |
| `world-runtime.md` §8.1 operational claimability list | Partial claimability checklist | **Superseded** by Amendment 0001 §9 and Amendment 0002 §2 |
| `world-runtime.md` §2.4 Timeline Logical State examples | Does not explicitly name chronology-budget consumption | **Augmented** by Amendment 0002 §3 |
| `world-runtime.md` §13 `Hard invariants after closure` | End-of-document hard-invariant list can be read as an independent specification layer | **Status changed** by Amendment 0002 §7: navigation/checklist aid subordinate to accepted Amendments and the canonical detailed topic sections |
| `runtime-contracts.md` §9.5 validation list | Requires `Event occurred_at == pinned World Time` validation on a Capability-supplied field | **Superseded** by Amendment 0001 §5 |
| `runtime-contracts.md` §10.1 `ProposedEvent` | Lists authoritative `occurred_at World Time` inside proposal | **Superseded** by Amendment 0001 §5 |
| `runtime-contracts.md` §14.11 operational claimability list | Missing chronology-budget/admission condition | **Superseded** by Amendment 0001 §9 and Amendment 0002 §2 |
| `runtime-contracts.md` §16.1 validation pipeline | Includes validation of Capability-supplied `occurred_at` | **Superseded** by Amendment 0001 §5 |
| `runtime-contracts.md` §17.2 public capability domains | Omits Ingress | **Augmented** by Amendment 0001 §6.2: `loom-api` includes Ingress service/domain |
| `runtime-contracts.md` §20.2 crate placement | Does not place Template/Birth validation authority | **Augmented** by Amendment 0001 §7 |
| `runtime-contracts.md` §22 `Normative v0 Rules` | End-of-document acceptance summary can be read as an independent specification layer | **Status changed** by Amendment 0002 §7: navigation/checklist aid subordinate to accepted Amendments and the canonical detailed topic sections |
| `governance.md` §15 `Normative Rules` | End-of-document mandatory acceptance list can be read as an independent specification layer | **Status changed** by Amendment 0002 §7: navigation/checklist aid subordinate to accepted Amendments and the canonical detailed topic sections |
| `implementation.md` §3 crate responsibilities | Does not place Template/Birth validation authority | **Augmented** by Amendment 0001 §7 |
| `implementation.md` §5.1 Loom API capability domains | Omits Ingress | **Augmented** by Amendment 0001 §6.2 |
| `implementation.md` §6.5 Storage and §13 Durable Work | `SKIP LOCKED` is constrained not to redefine the logical head, but the allowed cross-Timeline use vs forbidden same-Timeline skip is not explicit | **Materially augmented** by Amendment 0001 §4: `SKIP LOCKED` may distribute work across independent Timeline heads but may never skip a Timeline's logical head to claim its successor |
| `implementation.md` §12.2 Event time | Describes Capability-provided `occurred_at` equality contract | **Superseded** by Amendment 0001 §5 |
| `implementation.md` §12.3 operational claimability list | Partial claimability checklist | **Superseded** by Amendment 0001 §9 and Amendment 0002 §2 |
| `implementation.md` §19 CI Baseline | Lists both Ubuntu and macOS as current minimum CI environments | **Superseded** by Amendment 0002 §4 |
| `implementation.md` §21.5 ProposedEvent / CommittedEvent | Treats proposal occurrence time as Capability-provided | **Superseded** by Amendment 0001 §5 |

If a baseline clause is listed above, **do not implement it literally without applying the current Amendment authority**.

---

## 2. One canonical Scheduler claimability contract

Amendment 0001 §9 is the single canonical v0 claim/admission checklist.

The shorter lists in:

```text
world-runtime.md §8.1
runtime-contracts.md §14.11
implementation.md §12.3
```

are historical baseline summaries and are superseded.

Current contract:

```text
Semantic due-ness
= logical status == Pending
  AND effective_due_world_time <= Timeline.world_time

Scheduler claim/admission eligibility
= semantically due
  AND available_at <= PlatformTime.now
  AND no conflicting valid lease/fence
  AND owning semantic Capability is enabled by World Runtime Binding
  AND a compatible handler implementation can be assembled for execution
  AND chronology-budget/admission policy permits execution
```

No other document may maintain a shorter checklist as if it were independently complete.

A Runtime may internally distinguish “platform-operational claimability” from “scheduler admission policy”, but that internal decomposition cannot remove any condition above before a Work is actually admitted for execution.

---

## 3. Chronology Budget authority domain

### 3.1 Budget consumption is Timeline Logical State

The canonical same-World-Time chronology-budget consumption belongs to **Timeline Logical State**.

It is not Platform Operational State because it:

- affects whether future same-Timeline Scheduler execution may continue automatically;
- must survive process restart;
- must be replay/fork reconstructable;
- is scoped to a Timeline and WorldInstant;
- cannot reset merely because a worker, lease or process changes.

Conceptually, Timeline Logical State therefore includes:

```text
World Time
logical Durable Work + logical order
TimelineVersion / ancestry
chronology-budget consumption for the current/relevant WorldInstant
```

### 3.2 Minimum v0 consumption unit

The minimum v0 liveness budget counts successful **Scheduler-managed Work logical completions** at the same Timeline WorldInstant.

A scheduler Work that reaches a successful Runtime-owned Logical Commit and leaves the current Work from `Pending` consumes one chronology unit at that WorldInstant, regardless of whether that commit produced zero or many World Events.

This is sufficient to bound chains such as:

```text
Work -> Event -> Reaction -> Immediate Work -> ...
```

Optional stricter dimensions may later count reaction-derived schedules or compute/session usage, but those dimensions must declare their own authority domain. Pure technical retry attempts remain Platform Operational State and are already bounded separately by FailurePolicy; they are not silently reclassified as Timeline chronology.

### 3.3 Persistence and TimelineVersion

Chronology-budget consumption is recorded/reconstructable as part of the **same Logical Commit** that completes the Scheduler Work.

Therefore:

- it participates in the TimelineVersion advance of that Logical Commit;
- it does **not** require an additional second TimelineVersion increment solely for the counter update;
- replay restores the same consumption position;
- fork reconstructs consumption from ancestry at the fork position and then allows branch-local future consumption to diverge;
- when World Time advances to a later WorldInstant, the new coordinate begins its own budget accounting according to Runtime policy.

An implementation may materialize a counter for efficiency, but that materialization is a projection of Timeline Logical State, not an operational worker counter.

---

## 4. Current CI baseline

`implementation.md` §19 is superseded only for its current platform list.

The repository's current mandatory GitHub Actions baseline is:

```text
Ubuntu

python3 tools/check_architecture.py
cargo fmt --all -- --check
cargo check --workspace --all-targets --all-features
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace --all-features
cargo doc --workspace --no-deps with warnings denied
PostgreSQL 18 persistence contract tests where configured
```

macOS is **not currently a mandatory CI environment**. It may be reintroduced when cross-platform application/UI requirements justify it.

Architecture documentation must describe actual required validation separately from future desired coverage.

---

## 5. Missing-implementation blocking observability

When a semantically due logical head cannot execute because the active Runtime Revision cannot assemble a compatible handler implementation, Runtime must surface a distinct blocked condition through observability/control.

Conceptually:

```text
TimelineBlockedOnMissingImplementation
├── World / Timeline
├── blocked Work reference
├── owning Capability / handler requirement
├── active Runtime Revision reference
└── first/last observed platform metadata where useful
```

This status:

- does not consume a technical execution attempt merely because software is absent;
- does not clear the chronology barrier;
- does not become World Truth;
- is derivable from Timeline Logical State + current software availability and therefore need not become another semantic Timeline mutation;
- must be visible enough for an operator to restore compatible software or invoke the authorized logical terminalization path from Amendment 0001 §1.5.

`ChronologyBudgetExceeded` and `TimelineBlockedOnMissingImplementation` are both operator-visible liveness conditions, though they have different authority domains and recovery paths.

---

## 6. Amendment linkage rule going forward

Every accepted Architecture Amendment must include an **exact affected-clause index** whenever it supersedes or materially augments frozen text.

The Architecture Index must maintain a reverse supersession table sufficient for a reader/Agent to answer:

> “Is this baseline section still current as written?”

before turning the section into an implementation task.

Frozen baseline files may remain unchanged to preserve the historical snapshot. If they are not edited in place, the Index + Amendment reverse mapping is mandatory.

During re-planning:

1. read `docs/architecture/README.md` first;
2. resolve the supersession table for any baseline section being cited;
3. cite both the baseline section and the overriding Amendment when a task derives from an amended clause;
4. never quote a superseded checklist as the current acceptance contract.

---

## 7. Canonical-summary rule

The following frozen end-of-document sections have their **specification status changed** by this rule:

```text
world-runtime.md §13 Hard invariants after closure
runtime-contracts.md §22 Normative v0 Rules
governance.md §15 Normative Rules
```

They remain useful navigation/checklist aids, but they are not additional independent specification layers.

If a summary bullet and that document's detailed section differ, use:

```text
accepted Amendments
        ↓
canonical detailed topic section
        ↓
end-of-document summary/checklist
```

This prevents end-of-document hard-invariant/normative-rule summaries from becoming another set of competing specifications.

---

## 8. Re-planning gate

With Amendment 0002 accepted:

- baseline supersession is explicitly discoverable;
- claimability has one complete canonical list;
- chronology-budget state belongs to one authority domain;
- CI documentation matches current required coverage;
- missing implementation blockage is observable;
- summary-section status changes and material augmentations are present in the exact affected-clause index;
- no new architecture blocker is introduced by these corrections.

The next valid phase remains v0 implementation re-planning, followed by rebuilding Issues/tasks before code execution resumes.
