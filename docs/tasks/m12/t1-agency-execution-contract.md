---
task: M12-T1
issue: 121
status: planned
depends_on: [119]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M12-T1 — Agency Execution and Agent-Local Visibility Contract

## Goal
Freeze Agent identity/context/cognition/action/wake/provenance paths before any provider implementation.

## Implementation contract
- Prefer existing Entity identity + Agency metadata over a duplicate World object hierarchy.
- AgentWorldView/Context is deliberately restricted: allowed local state, explicit observations and bounded semantic retrieval; never wholesale BaseWorldView.
- `loom-agency` owns CognitiveExecutor/request/context/Decision/error SPI and may depend only on Core/Protocol as needed.
- V0 Decision is `Act(ActionInvocation)` or `NoAction`, never Event/Effect/Resolution/ValidatedResolution.
- Define cognition as M11 session/origin with executor/provider/model audit identifiers, plus durable wake representation using existing Runtime future mechanisms.
- Semantic retrieval/entropy remain Runtime-controlled/budgeted.

## Forbidden shortcuts
No vendor SDK, Agency→Runtime/Storage/API/Boundary edge, omniscient executor view, direct mutation output or separate Agent ledger.

## Acceptance checklist
- [ ] identity/config ownership is explicit;
- [ ] visibility boundary is normative;
- [ ] SPI/dependency direction is frozen;
- [ ] provenance/session/wake semantics are explicit;
- [ ] retrieval/entropy integration is bounded;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned as strict M12 architecture root.
