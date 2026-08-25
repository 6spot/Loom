# Loom V0 Operator Guide

This guide explains the runtime distinctions an operator must internalize to run, inspect and recover a Loom V0 deployment without violating architecture authority. Every distinction is normative (see `docs/architecture/README.md` authority map) and directly visible through public APIs.

## 1. Installed Capability vs World Runtime Binding vs Execution Assembly

These three names are frozen and must never be merged into a single “global registry” mental model (`docs/architecture/world-runtime.md` §3, `docs/architecture/glossary.md`).

| Concept | What it is | Lifecycle | Where it is seen |
| --- | --- | --- | --- |
| **Installed Capability** | Platform software availability: which Capability crates the current `Runtime Revision` + composition root (`apps/loom-server` + `capabilities/loom-neutral`) has compiled and registered in `CapabilityRegistry::assemble` | Changes only when the platform publishes/activates a new `Runtime Revision` | `catalog` (global), `capabilities` list of `AdminRuntimeRevision`, `ServerConfig::from_env` startup log |
| **World Runtime Binding** | Per-World immutable runtime metadata: which semantic Capability domains (and their semver requirements) this World is allowed to use after birth. Stored alongside `WorldId`, shared by all Timelines of that World | Set exactly once at `WorldTemplateDescriptor → ValidatedWorldBirthPlan` birth (`world create`); never mutated by later Template revisions or Revision activation | `catalog --world-id <world-id>` (Binding-filtered, global `--output` before subcommand: `loom --output human catalog --world-id <id>`), `TimelineSnapshot.binding`, `World Runtime Binding` row in PostgreSQL (`loom-storage`) |
| **Execution Assembly** | Exact software implementations pinned for one root `Execution Session`: `TimelineTarget` + `TimelineVersion` + `World Runtime Binding` + `Runtime Revision` + exact compatible Capability implementations + policy/services (+ Agency context where used) | Created at Session start; recorded immutably in Session provenance | `admin session get --session-id`, `admin session for-event`, `Session.assembly` in provenance |

Consequences:

- A Capability may be **installed** yet not **enabled** for a World whose Binding excludes it; a Template revision that adds a new Capability only affects **future Worlds**.
- Every semantic execution entry (Action dispatch, WorkHandler, Reaction expansion, semantic retrieval, per-World Catalog, subresolution) reads the complete persisted **Binding** first, requires the confirmed active **Revision**, and resolves the Assembly only after exact compatibility against the complete Binding (`VersionReq`). Missing or incompatible software is typed unavailable/error; it never synthesizes a Revision or weakens the Binding.
- `Installed-but-disabled` is an expected V0 semantics — the operator demonstrates it via multiple Template revisions (§2.5 of this guide) rather than by mutating existing Worlds.

## 2. World Time vs Platform Time

```text
World Time (WorldInstant)  = Timeline-local monotonic semantic time coordinate (Timeline Logical State)
Platform Time (i64)        = platform monotonic/time-of-day metadata for lease/retry/ingress bookkeeping (Operational State)
```

Laws (world-runtime §2.4, §7):

> No Timeline logical-state mutation without a Runtime-owned Logical Commit.
> World Time cannot be advanced by PlatformClock, `occurred_at` wall timestamps, retry backoff or lease expiry.

| Property | World Time | Platform Time |
| --- | --- | --- |
| Where | `TimelineSnapshot.world_time`, Event `occurred_at` stamped by Runtime at commit | `Work.lease_deadline`, `Work.available_at`, Ingress `received_at`, Session `started_at` |
| Mutation | Explicit Logical Commit `AdvanceWorldTime` when quiescent; consumed alongside Work completion in same Logical Commit (`Chronology Budget`) | Sampled by the application via `PlatformClock::now_milli` for claim/fence bookkeeping |
| Operator control | `admin world-time advance --world --timeline --expected-head-seq --expected-state-rev --current --next` (CAS-guarded by expected `TimelineVersion`) | `LOOM_WORKER_LEASE_MS`, `LOOM_WORKER_RETRY_BACKOFF_MS`, `LOOM_WORKER_POLL_MS` (non-secret env) |

A common mis-operation is to set a large retry backoff and assume `World Time` will catch up automatically. It will not — the Timeline remains at the due head's `effective_due_world_time` until the Scheduler resolves it.

## 3. Logical Work vs lease / retry

```text
Logical Work lifecycle  = Timeline Logical State: Pending / Completed / Dead / Cancelled + effective_due_world_time + logical_schedule_order + TimelineVersion
Operational Work state  = Platform Operational State: lease_deadline / fence / attempt_count / last_error / available_at
```

- **Semantic due-ness** is purely logical: `Pending && effective_due_world_time <= Timeline.world_time`. It does not depend on lease or retry.
- **Operational claimability** adds the common v0 checklist (Amendment 0001 §9 + Amendment 0002 §2) on top of due-ness: `available_at <= now`, lease unfenced or reclaimable, handler Session assertable, bound-aware, etc. Agency Wake adds its target-specific compatibility (Amendment 0003 §3.2) after this common checklist.
- `FailurePolicy` is bounded; `Dead`/`Cancelled` are Logical Commits (`AdminTerminalizeWorkRequest`), not retry loops. Automatic technical retry never loops forever — a poison Work exhausts the policy and becomes a visible liveness condition requiring operator terminalization or software correction.
- A crash after claim leaves the Work `Pending` with a stale fence; after lease expiry a later worker reclaims it with a newer fence. The stale fence cannot retry, complete or terminalize.

Inspect: `loom --admin-token $LOOM_ADMIN_TOKEN --output human admin timeline status --world <world> --timeline <timeline>` (logical status + budget; global `--admin-token` before subcommand), `loom --admin-token $LOOM_ADMIN_TOKEN --output human admin work terminalize --world <world> --timeline <timeline> --work-id <work> --expected-head-seq <seq> --expected-state-rev <rev> --terminal-state dead` (or `cancelled`).

## 4. Head-of-line chronology barrier, quiescence and Chronology Budget

**Head-of-line barrier:** when the logical head is semantically due, later Work on the same Timeline cannot be claimed or executed before it, and `World Time` cannot be advanced past it. `SKIP LOCKED` helps distribute work across *independent* Timeline heads but never skips a logical head within one Timeline (Amendment 0001 §4).

**Quiescence:** a Timeline is quiescent iff it has no semantically due `Pending` Work (`Scheduler::is_quiescent`). Only then may an explicit `AdvanceWorldTime` Logical Commit occur.

**Chronology Budget:** a safety/liveness counter (`LOOM_RUNTIME_MAX_CHRONOLOGY_COMPLETIONS` / `ChronologyBudgetPolicy`) that bounds how many Scheduler-managed completions (Immediate/Reaction/Agency Wake) may occur at the same `WorldInstant`. Its consumption (`chronology_consumed`) is Timeline Logical State — recorded in the same Logical Commit as Work completion and replayed/reconstructed through the Logical Journal, not a volatile worker counter. Total completion count is the minimum safe dimension; `causal/derivation` depth may be added as policy dimensions later.

Behavior when exhausted: the Scheduler stops further automatic progress at that instant but **does not** advance `World Time` past due obligations to force progress. The operator must either raise the budget (configuration) or terminalize the head. `ChronologyBudgetExceeded` and `TimelineBlockedOnMissingImplementation` are both operator-visible liveness conditions with distinct recovery paths (Amendment 0002 §4).

## 5. Missing implementation and terminalization

`TimelineBlockedOnMissingImplementation` occurs when the semantically due logical head cannot be assembled because the active `Runtime Revision` lacks a compatible implementation for the required execution target (Capability `WorkHandler` vs Agency Wake's `CognitiveExecutor`/`AgentWorldView` context builder). The Timeline is blocked, not failed; `available_at` is not consumed; the chronology barrier remains.

Observe (global `--admin-token` before subcommand; `missing-implementation` requires `--work-id`):

```bash
cargo run -p loom-cli -- --admin-token $LOOM_ADMIN_TOKEN --output human admin timeline missing-implementation --world $WORLD --timeline $TIMELINE --work-id 00000000-0000-0000-0000-000000000070
cargo run -p loom-cli -- --admin-token $LOOM_ADMIN_TOKEN --output human admin timeline status --world $WORLD --timeline $TIMELINE
```

Recovery paths (mutually exclusive, both explicit Logical Commits):

1. **Provide compatible software** — publish and activate a new `Runtime Revision` containing the required capability/provider implementation; the Scheduler will then admit the same head on the next drive (requires `LOOM_SCHEDULER_WORLD_ID`/`TIMELINE_ID` to be set and the server restarted, see quickstart §3.5).
2. **Authorized terminalization** — an operator with `AdminOperation::TerminalizeWork` authority explicitly moves `Pending → Dead | Cancelled` via (global `--admin-token` before subcommand; `--expected-head-seq`/`--expected-state-rev` are mandatory CAS guards; `--terminal-state` is `dead` or `cancelled`):

```bash
cargo run -p loom-cli -- --admin-token $LOOM_ADMIN_TOKEN --output human admin work terminalize --world $WORLD --timeline $TIMELINE --work-id 00000000-0000-0000-0000-000000000070 --expected-head-seq 2 --expected-state-rev 2 --terminal-state dead
```

A terminalized Work is not resurrected; a new Work must be created with provenance/origin reference to the old one if another attempt is desired (Amendment 0001 §1.5).

## 6. Runtime Revision / Session provenance

| Artifact | Records | Command |
| --- | --- | --- |
| **Runtime Revision** | Immutable publication: `revision_id`, `published_at`, `core_build_ref`, `loom_version`, exact `capabilities[]` (capability_id/implementation_id/version/loom_compatibility), policy ids, `change_summary`, `semantic_behavior_changed`, plus per-revision `generation` CAS on the active pointer | `loom --admin-token $LOOM_ADMIN_TOKEN --output human admin revision list` / `get --revision-id …` / `activate --revision-id … --expected-generation …` (global `--admin-token` before `admin`) |
| **Execution Session** | Per root execution: `TimelineTarget`, pinned `TimelineVersion`, pinned `World Time`, `Execution Assembly`, `ReadSet`/subresolution call graph, entropy samples, `ExecutionResult`, lifecycle `Started/Committed/NoChange/Rejected/Failed/Blocked` | `loom --admin-token $LOOM_ADMIN_TOKEN --output human admin session get --session-id <id>`; `loom --admin-token $LOOM_ADMIN_TOKEN --output human admin session for-event --timeline <timeline> --event-id <event>` |
| **Event ↔ Session link** | Atomic `Event → producing Session` persistence (M9 tasks 183/184) | `loom --output human history event --timeline <timeline> --event-id <event>` (or `--event-ref <ref>`) → producing session id + session inspect |
| **Cognitive evidence** | Per observation `ordinal`, pinned executor/provider/model revision, `AdminDecisionReusePolicy` (`Resample` vs `ReuseDeterministic`), `AdminCognitiveDisposition` (`Fresh/Reused/Discarded`), context cost, `context_read_set` | Session `cognitive_observations[]` projection |

A new Revision never mutates history, Binding or `World Time`; it only affects *new* compatible Sessions. The active pointer's `generation` prevents lost-update activation races.

## 7. Replay vs rerun

| Mode | What happens | Produces new Events? | Uses new software? |
| --- | --- | --- | --- |
| **Replay** | Deterministic reconstruction of committed `World History` + Timeline Logical State (`World Time`, `Work lifecycle/order`, `chronology_consumed`, `ancestry`) for any committed `TimelineVersion`, through the frozen `Logical Journal` — no Capability code is executed | No | No — exact pinned Revision/Assembly is historical |
| **Rerun** | Re-executing resolvers via a *new* `Execution Session` against a (possibly newer) `Runtime Revision`/Assembly; result enters history via a new Logical Commit | Yes, if committed | Yes, if a new Revision has been activated |

Replay is observable via `history events/event`, `facet get` at historical versions, and `timeline inspect` showing reconstructed `world_time`/`chronology_consumed`. Rerun is an explicit new invocation (`action invoke`, `admin agency schedule-wake`, reaction-generated Work) that must pass the same Runtime authority gate. Confusing the two would violate “no semantic mutation without committed Event”.

## 8. Fork ancestry and branch isolation

A Timeline fork is a Logical Commit that clones `Timeline Logical State` history and ancestry:

- `ForkTimelineRequest { source: TimelineTarget, source_version?: TimelineVersion }` (`cargo run -p loom-cli -- --output human timeline fork --world <world> --timeline <timeline> [--source-version <seq:rev>]`).
- Parent Binding, `World Time`, `chronology_consumed`, `TimelineVersion` lineage and branch-local `Pending` Works are cloned; `Platform Operational State` (lease/fence/retry) is not forked — child Works start with fresh operational state.
- `TimelineAncestry`/`TimelineVersion`/`fork_position` are immutable, queryable via `history causes/effects/walk` (`CausalTraversal` with `CausalDirection::Ancestors|Descendants`).
- Branch-local Events/`Work`/`Session` provenance never leak across branches; the storage tests prove restart/replay/fork isolation (`crates/loom-storage/tests/postgres_work.rs`, `postgres_restart_resume`).

Historical fork (`source_version` at an older committed position) preserves the parent Binding as of that position; head fork without explicit version uses the current head as a convenience default.

## 9. Agent visibility and CAS resample policy

**AgentWorldView** is a subjective, Binding-checked projection built by Runtime mediation (§3 Agency contracts, Amendment 0003 §3):

- It is **not** a raw `Storage` read; it uses `AgentWorldViewBuilder` with `ContextBudget` (default `128 items / 65536 bytes`) and is scoped to the Session's pinned `TimelineVersion`/`World Time`/`Assembly`.
- Capability `WorkHandler` never receives a `CognitiveExecutor`; only the Scheduler-managed Agency Wake path owns the cognition lifecycle (claim → pin Session → build view → run `CognitiveExecutor` → produce `Decision::Act|NoAction` → route Act back through normal `ActionInvocation` authority).

**CAS competition and reuse policy:**

Successful `v0` Logical Commits on one Timeline serialize at Timeline scope via `TimelineVersion` CAS (Amendment 0003 §5). A Wake that computed `Decision::Act` for version `V` and lost the race to another commit at `V+1` cannot commit at stale `V`; the stale result is retained as a `Discarded` `AdminCognitiveObservation` and is part of Session provenance.

Two explicit policies (pinned in `ExecutionPolicy` / visible in every observation):

| Policy | Executor calls per CAS loss | Provenance `disposition` | When to use |
| --- | --- | --- | --- |
| `Resample` (default v0) | 2× — old discarded, new `Fresh` invocation | `Discarded` + `Fresh` | General-purpose; pays cognition cost to avoid stale context |
| `ReuseDeterministic` | 1× — revalidated deterministic decision | `Discarded` + `Reused` | Only when the executor/policy is explicitly deterministic and reuse has fresh `TimelineVersion`/`WorldTime`/`context_read_set` (the reused record records the fresh coordinate, not the discarded coordinate) |

A hidden or accidental reuse/resampling is forbidden; the policy choice is recorded in `Session.cognitive_observations[].policy.decision_reuse` and in `ExecutionSessionStore` evidence. The capacity envelope (`docs/capacity-envelope.md`, `docs/tasks/m11/t3-capacity-benchmarks.md` §Cognition CAS waste) measures both: 8 armed conflicts show `Resample` at 16 calls / 8 discards / 8 fresh vs `ReuseDeterministic` at 8 calls / 8 discards / 8 reused.

Semantic rejection of `Decision::Act` itself (capability `Rejection`) correctly completes the same Wake as a determined `NoChange` outcome — it is not a technical failure requiring automatic resample. Reconsideration is a **new Wake**.
