# Loom Development Guardrails

This repository is architecture-first. Before changing code, crate dependencies, public APIs, Capability contracts or Runtime behavior, read:

1. `docs/principles.md`
2. `docs/architecture/core.md`
3. `docs/architecture/implementation.md`
4. `docs/architecture/runtime-contracts.md`
5. `docs/architecture/governance.md`
6. `docs/tasks/README.md`
7. the active task file under `docs/tasks/<milestone>/` for the work being implemented

`docs/architecture/governance.md` is normative for Rust dependency direction and public capability exposure. `docs/tasks/README.md` is normative for repository task status and completion evidence.

## Non-negotiable rules

- Do not translate runtime call direction into Cargo dependency direction.
- `loom-core` is World Language, not a shared DTO/common crate.
- Shared untrusted execution protocol belongs in `loom-protocol`.
- External consumption contracts belong in `loom-api`.
- Capability/Agency contracts may depend on Core/Protocol; they must not depend on Runtime.
- Runtime must not depend on concrete Storage, Boundary, Capability implementation or provider implementation crates.
- Storage implements Runtime-owned persistence ports; Runtime must not import `loom-storage`.
- Boundary adapts transport to `loom-api`; it must not route directly to Runtime internals or Capability resolvers.
- Capability registers semantics only. It must not register HTTP/SSE/WebSocket/gRPC routes, CLI commands, GPUI public engine surfaces or SDK endpoints.
- All external consumers use the unified Loom API contract.
- `ValidatedResolution` is Runtime-owned authority. Do not move it into a shared crate for convenience.
- World mutation still follows `Resolution -> validation -> ValidatedResolution -> Timeline Commit`.
- Every public Core/Protocol/API/Runtime/Capability abstraction requires semantic Rust doc comments as defined in `runtime-contracts.md`.
- Every implementation task must have one repository task file. Set it to `in_progress` when work starts, and do not close the task as completed until the file is `completed` with PR, merge SHA and verification evidence as required by `docs/tasks/README.md`.

## Task records

GitHub issues are the collaboration surface; repository task files are the durable audit trail. Their status must agree.

When starting an implementation task, update its task file in the implementation branch/PR. When completing it, satisfy the task-file acceptance checklist, record completion evidence, mark it `completed`, and close the GitHub issue as completed. If the final merge SHA is only known after merge, record it immediately in a follow-up audit update.

Do not mark duplicate, cancelled or superseded work as completed; record the reason and replacement task instead.

## Architecture changes

A normal feature must not silently add a forbidden dependency edge or a new public exposure path.

If the current architecture genuinely cannot express a requirement, change the relevant architecture contract first, explain why existing mechanisms are insufficient, update architecture checks, and only then implement the new design.

Do not make the documentation conform to already-written violating code.
