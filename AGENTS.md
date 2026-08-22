# Loom Development Guardrails

This repository is architecture-first. Before changing code, crate dependencies, public APIs, Capability contracts or Runtime behavior, read:

1. `docs/vision.md`
2. `docs/principles.md`
3. `docs/architecture/core.md`
4. `docs/architecture/layers.md`
5. `docs/architecture/world-runtime.md`
6. `docs/architecture/runtime-contracts.md`
7. `docs/architecture/evolution.md`
8. `docs/architecture/implementation.md`
9. `docs/architecture/governance.md`
10. `docs/tasks/README.md`
11. the active task file under `docs/tasks/<milestone>/` only after the post-freeze implementation plan has been rebuilt and activated

`docs/architecture/world-runtime.md` is normative for World Runtime Binding, World Time progression, Timeline Logical Commit, Durable Work chronology and Execution Session/software binding. `docs/architecture/governance.md` is normative for Rust dependency direction, authority type placement and public capability exposure. `docs/tasks/README.md` is normative for repository task status and completion evidence once the rebuilt implementation plan is active.

## Current architecture status

**Loom v0 architecture is frozen.**

The freeze includes:

- World Runtime Binding ownership and installed-vs-enabled semantics;
- explicit World Time progression;
- Timeline Logical Commit authority;
- semantic Work due-ness vs operational claimability;
- persistent same-Timeline Durable Work ordering;
- head-of-line and due-work quiescence barriers;
- Execution Session / Runtime Revision / exact implementation binding;
- replay/fork authority domains;
- Capability host nondeterminism boundaries;
- the existing Cargo dependency DAG and authority placement rules.

The next phase is **re-planning**, not immediate implementation.

Until the new V0 implementation plan, Issues and task records are rebuilt from the frozen architecture:

- do not start a new implementation task merely because an existing GitHub Issue/task record says it is next;
- do not reinterpret the old roadmap as still authoritative;
- do not make code changes to “fill gaps” before the new plan explicitly covers them;
- architecture fixes require a new architecture review before implementation;
- once the new plan is activated, implementation tasks again follow the normal Issue + task-record workflow.

## Non-negotiable rules

- Do not translate runtime call direction into Cargo dependency direction.
- `loom-core` is World Language, not a shared DTO/common or Runtime-authority crate.
- Shared untrusted execution protocol belongs in `loom-protocol`.
- External consumption contracts belong in `loom-api`.
- Capability/Agency contracts may depend on Core/Protocol; they must not depend on Runtime.
- Runtime must not depend on concrete Storage, Boundary, Capability implementation or provider implementation crates.
- Storage implements Runtime-owned persistence ports; Runtime must not import `loom-storage`.
- Boundary adapts transport to `loom-api`; it must not route directly to Runtime internals, Capability resolvers, World Binding storage, World-Time persistence fields or Work claim authority.
- Capability registers semantics only. It must not register HTTP/SSE/WebSocket/gRPC routes, CLI commands, GPUI public engine surfaces or SDK endpoints.
- All external consumers use the unified Loom API contract.
- `ValidatedResolution` is Runtime-owned authority. Do not move it into a shared crate for convenience.
- **Installed Capability != enabled Capability for a World.** Global registry presence is software availability, not World authorization.
- Runtime must enforce the target World Runtime Binding for Action, WorkHandler, Reaction, subresolution, semantic retrieval and World-scoped discovery.
- World Runtime Binding is World-level and shared by its Timelines in v0; it stores semantic compatibility/configuration requirements, not a permanent exact implementation pin.
- Every root world-affecting execution pins an Execution Session / Execution Assembly; do not switch Runtime Revision or exact Capability implementation mid-session.
- **No semantic World State mutation without a committed Event.** `WorldEffect` never commits standalone.
- **No Timeline logical-state mutation without a Runtime-owned logical commit.** World Time, logical Work and Work ordering are not fake domain Events.
- World Time is explicit Timeline logical state. Do not derive it from `max(Event.occurred_at)`, PlatformClock, database `NOW()` or worker sleep duration.
- Capability may read pinned World Time but cannot advance it and must never receive PlatformClock as World time.
- Work effective due time uses World Time; retry/lease `available_at` uses Platform Time. Never merge the two clocks.
- **Semantic due-ness != operational claimability.** Retry backoff, lease state, worker availability and temporary implementation availability do not change whether a Pending Work is already due in World Time.
- Same-Timeline Scheduler Work order is persistent `(effective_due_world_time, logical_schedule_order)` semantics. Never derive it from UUID/WorkId, database natural row order, worker race, wall-clock race or lease acquisition speed.
- Only the semantically due logical head may be Scheduler-admitted. Later Work must not skip it because the head is retrying, leased, unavailable or temporarily lacks a compatible implementation.
- Any semantically due Pending Work is a World-Time advancement barrier. `AdvanceWorldTime` requires scheduler quiescence.
- Work leaves that barrier only through a Runtime-owned logical transition to `Completed`, `Cancelled` or `Dead`; technical retry alone never clears it.
- Platform claim/lease/fence/retry metadata must not become World History or Timeline logical history.
- `FOR UPDATE SKIP LOCKED` or similar SQL primitives are implementation tools; they must not redefine logical next-Work semantics.
- v0 Capability `ResolutionContext` may expose controlled reads/subresolution/Entropy where defined, but not raw RNG, network/provider client, generic cognition handle, Storage or Commit authority.
- v0 cognition stays behind `loom-agency`: CognitiveExecutor produces Decision; `Decision::Act` re-enters the normal Action authority path.
- Replay reconstructs semantic State from committed frozen Event Effects and World Time/logical Work/order from Timeline logical history; replay never re-runs current Resolver, Entropy or Cognition.
- Fork preserves World identity/Runtime Binding, reconstructs fork-point State/World Time/logical Future/order, and resets branch-local operational lease/retry state.
- Every public Core/Protocol/API/Runtime/Capability abstraction requires semantic Rust doc comments as defined in `runtime-contracts.md`.

## Task records

GitHub issues are the collaboration surface; repository task files are the durable audit trail. Their status must agree **once the post-freeze implementation plan is active**.

When starting an approved implementation task, update its task file in the implementation branch/PR. When completing it, satisfy the task-file acceptance checklist, record completion evidence, mark it `completed`, and close the GitHub issue as completed. If the final merge SHA is only known after merge, record it immediately in a follow-up audit update.

Do not mark duplicate, cancelled or superseded work as completed; record the reason and replacement task instead.

The architecture freeze itself does not rewrite task records or Issues. Rebuilding them is the next planning phase.

## Architecture changes

A normal feature must not silently add a forbidden dependency edge, a new public exposure path, a new authority path, a different World/Timeline truth model, or a different scheduler chronology.

If the frozen architecture genuinely cannot express a requirement, change the relevant architecture contract first, explain why existing mechanisms are insufficient, update architecture checks, and only then implement the new design after a new architecture review.

Do not make the documentation conform to already-written violating code.
