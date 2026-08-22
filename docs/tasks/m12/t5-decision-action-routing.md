---
task: M12-T5
issue: 125
status: planned
depends_on: [124]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M12-T5 — Route Decision::Act Through Action Authority

## Goal
Ensure cognition changes World only by re-entering normal semantic Action execution.

## Required implementation
- `Decision::Act` follows the same World binding, schema, resolver/subresolution, validation and atomic commit path as ordinary Action.
- Freeze/query cognition→Action session/provenance relationship exactly as #121/#113 requires.
- Preserve Agent origin in provenance without silently modifying arbitrary Action input.
- `NoAction` finalizes provenance with no Event/Timeline logical mutation.
- Invalid/disabled/unregistered decisions fail typed and cannot be repaired by direct executor commit.

## Forbidden shortcuts
No direct Event/Effect/Resolution, Agent-specific Capability bypass, hidden actor-field injection or fake NoAction Event.

## Acceptance checklist
- [ ] Act uses normal Action authority;
- [ ] invalid/disabled Action cannot mutate World;
- [ ] NoAction changes no logical World state;
- [ ] cognition→Action provenance is queryable;
- [ ] branch/world capability bindings are respected;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after cognitive gateway.
