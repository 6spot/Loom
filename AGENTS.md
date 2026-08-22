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
11. the active task file under `docs/tasks/<milestone>/` only after architecture closure has been approved and implementation planning has resumed

`docs/architecture/world-runtime.md` is normative for World Runtime Binding, World Time progression, Timeline Logical Commit and Execution Session/software binding. `docs/architecture/governance.md` is normative for Rust dependency direction, authority type placement and public capability exposure. `docs/tasks/README.md` is normative for repository task status and completion evidence once implementation planning is active.

## Current architecture closure gate

Implementation expansion is intentionally paused while the World Runtime Closure architecture is reviewed.

Until that closure is explicitly approved and the implementation plan/Issues are rebuilt:

- do not start a new implementation task merely because an existing GitHub Issue/task record says it is next;
- do not reorder or silently reinterpret the old roadmap inside code changes;
- do not make implementation changes to “prove” an undecided architecture point;
- architecture/documentation work may proceed on an isolated review branch;
- after architecture approval, rebuild implementation ordering and task records before resuming code.

## Non-negotiable rules

- Do not translate runtime call direction into Cargo dependency direction.
- `loom-core` is World Language, not a shared DTO/common or Runtime-authority crate.
- Shared untrusted execution protocol belongs in `loom-protocol`.
- External consumption contracts belong in `loom-api`.
- Capability/Agency contracts may depend on Core/Protocol; they must not depend on Runtime.
- Runtime must not depend on concrete Storage, Boundary, Capability implementation or provider implementation crates.
- Storage implements Runtime-owned persistence ports; Runtime must not import `loom-storage`.
- Boundary adapts transport to `loom-api`; it must not route directly to Runtime internals, Capability resolvers, World Binding storage or World-Time persistence fields.
- Capability registers semantics only. It must not register HTTP/SSE/WebSocket/gRPC routes, CLI commands, GPUI public engine surfaces or SDK endpoints.
- All external consumers use the unified Loom API contract.
- `ValidatedResolution` is Runtime-owned authority. Do not move it into a shared crate for convenience.
- **Installed Capability != enabled Capability for a World.** Global registry presence is software availability, not World authorization.
- Runtime must enforce the target World Runtime Binding for Action, WorkHandler, Reaction, subresolution, semantic retrieval and World-scoped discovery.
- World Runtime Binding is World-level and shared by its Timelines in v0; it stores semantic compatibility/configuration requirements, not a permanent exact implementation pin.
- Every root world-affecting execution pins an Execution Session / Execution Assembly; do not switch Runtime Revision or exact Capability implementation mid-session.
- **No semantic World State mutation without a committed Event.** `WorldEffect` never commits standalone.
- **No Timeline logical-state mutation without a Runtime-owned logical commit.** World Time and logical Work are not fake domain Events.
- World Time is explicit Timeline logical state. Do not derive it from `max(Event.occurred_at)`, PlatformClock, database `NOW()` or worker sleep duration.
- Capability may read pinned World Time but cannot advance it and must never receive PlatformClock as World time.
- Work `due_world_time` uses World Time; retry/lease `available_at` uses Platform Time. Never merge the two clocks.
- Platform claim/lease/fence/retry metadata must not become World History or Timeline logical history.
- v0 Capability `ResolutionContext` may expose controlled reads/subresolution/Entropy where defined, but not raw RNG, network/provider client, generic cognition handle, Storage or Commit authority.
- v0 cognition stays behind `loom-agency`: CognitiveExecutor produces Decision; `Decision::Act` re-enters the normal Action authority path.
- Replay reconstructs semantic State from committed frozen Event Effects and World Time/logical Work from Timeline logical history; replay never re-runs current Resolver, Entropy or Cognition.
- Fork preserves World identity/Runtime Binding, reconstructs fork-point State/World Time/logical Future, and resets branch-local operational lease/retry state.
- Every public Core/Protocol/API/Runtime/Capability abstraction requires semantic Rust doc comments as defined in `runtime-contracts.md`.

## Task records

GitHub issues are the collaboration surface; repository task files are the durable audit trail. Their status must agree **once the post-closure implementation plan is active**.

When starting an approved implementation task, update its task file in the implementation branch/PR. When completing it, satisfy the task-file acceptance checklist, record completion evidence, mark it `completed`, and close the GitHub issue as completed. If the final merge SHA is only known after merge, record it immediately in a follow-up audit update.

Do not mark duplicate, cancelled or superseded work as completed; record the reason and replacement task instead.

The current architecture closure review does not itself rewrite task records or Issues. That happens only after the architecture is accepted and the implementation plan is rebuilt.

## Architecture changes

A normal feature must not silently add a forbidden dependency edge, a new public exposure path, a new authority path, or a different World/Timeline truth model.

If the current architecture genuinely cannot express a requirement, change the relevant architecture contract first, explain why existing mechanisms are insufficient, update architecture checks, and only then implement the new design after review.

Do not make the documentation conform to already-written violating code.
