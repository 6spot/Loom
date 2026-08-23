# Loom Development Guardrails

This repository is architecture-first. `AGENTS.md` is an execution index, **not an independent architecture specification**.

Before changing code, crate dependencies, public APIs, Capability contracts or Runtime behavior, read:

1. `docs/architecture/README.md` — document authority / precedence / reverse supersession / amendments / open questions
2. `docs/architecture/glossary.md` — canonical terminology
3. `docs/vision.md`
4. `docs/principles.md`
5. the canonical architecture documents required by the task (`core.md`, `layers.md`, `world-runtime.md`, `runtime-contracts.md`, `evolution.md`, `implementation.md`, `governance.md`)
6. **all accepted `docs/architecture/amendments/*.md` that affect the cited baseline sections**
7. `docs/tasks/README.md` and the active task file only after the post-architecture implementation plan is rebuilt and activated

Do not treat a summary in README, Principles, AGENTS or an old Issue as authority when the Architecture Index points to a canonical source.

Before converting any frozen baseline section into an implementation task, **resolve it against the Architecture Index reverse supersession table**. If that section is amended, the task must cite the overriding Amendment as part of its acceptance basis.

## Current architecture status

The Loom v0 architecture baseline is frozen and may be changed only through explicit Architecture Amendments.

Accepted Amendment 0001 closes runtime liveness/boundary gaps around:

- bounded Runtime Work failure policy and terminal exit;
- same-World-Time chronology budget;
- Runtime ownership of Scheduler/Timeline Driver logic;
- `SKIP LOCKED` scope;
- Runtime ownership of Event occurrence-time stamping;
- Ingress as a reliable external envelope around the normal Action path;
- World Template technical placement / `ValidatedWorldBirthPlan` authority;
- Intent / Trigger / Reaction / Actor / Agent terminology reconciliation.

Accepted Amendment 0002 closes amendment/linkage gaps around:

- exact baseline-clause supersession mapping;
- one complete Scheduler claim/admission checklist;
- Chronology Budget consumption as Timeline Logical State;
- current mandatory CI baseline (Ubuntu; macOS currently deferred);
- `TimelineBlockedOnMissingImplementation` observability;
- mandatory exact affected-clause indexes for future Amendments.

Accepted Amendment 0003 closes the remaining Agency/read-path execution gaps around:

- Agent Wake as a Scheduler-managed durable execution obligation rather than a hidden timer/provider callback;
- Runtime-owned Agent-wake Session/claim/provenance/commit orchestration while `loom-agency` owns subjective context/cognition contracts;
- AgentWorldView production through Runtime-mediated, World-Binding-checked reads;
- target-specific Capability Work vs Agency Wake compatibility at Scheduler admission;
- pinned `BaseWorldView` semantics without requiring eager complete World materialization;
- explicit v0 Timeline-wide successful-commit serialization and deferred fine-grained validation;
- explicit deferral of worker executor/`Send`-`Sync` topology and historical checkpoint acceleration.

The next phase is **re-planning**, not resuming the old roadmap by inertia.

Until the rebuilt V0 implementation plan, Issues and task records are activated:

- do not start implementation merely because an old Issue/task says it is next;
- do not reinterpret old task ordering as authoritative;
- do not change code to prove or invent architecture not already covered by the canonical docs/amendments;
- do not modify Issues/tasks as part of architecture cleanup unless the planning phase explicitly begins.

## Mandatory execution rules

Rather than duplicating every architecture invariant here, follow these canonical sources:

- Core/world semantics: `docs/architecture/core.md`
- Semantic layers: `docs/architecture/layers.md`
- World Binding / World Time / Logical Commit / Session / baseline Work chronology: `docs/architecture/world-runtime.md`
- Detailed Runtime/Capability execution protocol: `docs/architecture/runtime-contracts.md`
- Runtime liveness / failure / Scheduler / Ingress / Template semantics: `docs/architecture/amendments/0001-runtime-liveness-and-boundaries.md`
- Supersession mapping / chronology-budget authority / current CI / blocked-state observability: `docs/architecture/amendments/0002-supersession-and-authority-linkage.md`
- Agent Wake orchestration / pinned-read semantics / Timeline commit-serialization clarification: `docs/architecture/amendments/0003-agency-execution-and-pinned-read-boundary.md`
- Software evolution: `docs/architecture/evolution.md`
- Cargo DAG / public exposure / authority type placement: `docs/architecture/governance.md`
- Technical realization / persistence / dependency choices: `docs/architecture/implementation.md`

A few repository-wide guardrails are worth repeating because violating them is almost always a wrong-layer implementation:

- Runtime authority must not be moved into a shared crate for convenience.
- Capability/Agency contracts must not depend on Runtime.
- Runtime must not depend on concrete Storage/Boundary/Capability/provider implementations.
- Storage implements Runtime-owned ports; it does not define World truth, Timeline chronology or scheduler order.
- Boundary/Application consumers use `loom-api`; no Capability-specific public bypass.
- Semantic World State mutation requires committed Event + frozen Effects.
- Timeline logical mutation requires Runtime-owned Logical Commit.
- PlatformClock/lease/retry/DB order must not become World Time or same-Timeline chronology.
- Capability `WorkHandler` / `ResolutionContext` must not gain a generic CognitiveExecutor/provider/network handle to implement Agent autonomy; Agent Wake follows Amendment 0003.
- A pinned `BaseWorldView` means one logical snapshot position, **not** mandatory full-World eager loading. Any scalable read path must still prevent mixed-revision observations and persistence-authority leakage.
- Successful v0 Logical Commits serialize at Timeline scope; do not claim fine-grained same-Timeline write concurrency until an accepted Amendment changes that authority model.
- Public Core/Protocol/API/Runtime/Capability abstractions require semantic Rust documentation sufficient to recover ownership/authority without chat history.

For exact terminology such as semantic due-ness, operational claimability, Logical Head, Chronology Budget, Agent Wake, Pinned Read Boundary, Timeline-wide Commit Serialization, Ingress, Intent, Trigger, Reaction, Actor and Agent, use `docs/architecture/glossary.md` instead of inventing local meanings.

For Scheduler claim/admission, do **not** reconstruct a checklist from older baseline summaries. Use Amendment 0001 §9 + Amendment 0002 §2; when the logical head is Agency Wake, also apply Amendment 0003 §3.2 target-specific compatibility.

## Local PostgreSQL integration tests

Development on the standard Linux host reuses the repository-managed local PostgreSQL 18 + pgvector test service instead of starting an ad-hoc database for each task.

- Start or inspect the service with `bash tools/postgres-test.sh up` / `status`.
- Run PostgreSQL-dependent tests through `bash tools/test.sh ...`; this loads `.env.test.local` and requires PostgreSQL integration tests rather than silently skipping them.
- Do not invent a different local test URL or launch another PostgreSQL container when the repository service is available.
- The configured URL is a control database. Test fixtures create/drop isolated child databases, so the configured role must retain the required database-creation privileges.
- See `docs/development/postgres-tests.md` for lifecycle, networking and CI details.

## Task records

GitHub Issues are the collaboration surface; repository task files are the durable audit trail **once the rebuilt implementation plan is active**.

When an approved implementation task starts, update its task file in the implementation branch/PR. When completing it, satisfy its acceptance checklist, record evidence, mark it completed, and close the matching GitHub Issue. Duplicate/cancelled/superseded work must record its reason/replacement rather than being marked completed.

Architecture work itself does not silently rewrite implementation task history.

## Architecture changes

If an implementation requirement cannot be expressed by the frozen baseline + accepted Amendments:

1. stop implementation of that violating design;
2. write/review an Architecture Amendment with the concrete counterexample;
3. include the exact affected document + section index;
4. update the Architecture Index reverse supersession table and glossary as required;
5. only then re-plan and implement.

Do not make architecture documentation conform to already-written violating code.
