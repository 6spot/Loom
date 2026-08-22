---
task: M5-T1
issue: 68
status: planned
depends_on: [66]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M5-T1 — Timeline Ancestry, Fork-Point and EventRef Contract

## Goal
Freeze immutable Timeline ancestry, fork-point, child ordering and cross-Timeline causal-reference semantics.

## Implementation contract
- Define parent Timeline + parent fork `TimelineVersion` representation.
- Child references shared ancestry; ancestor Event rows are never copied.
- Preserve fork-point Entity/Relationship identities and define branch-local Event sequencing.
- Introduce explicit Timeline-aware `EventRef { timeline_id, event_id }` semantics.
- Permit causes only from current Timeline or visible ancestors at/before descendant fork boundaries; reject siblings/unrelated Worlds/ancestor future.
- Clone logical Pending Work with new WorkIds while preserving semantic obligation/origin and resetting lease/fence/retry metadata.

## Forbidden shortcuts
No platform-time fork point, copied ancestor Events, reused parent WorkIds or EventId-only causal assumptions.

## Acceptance checklist
- [ ] ancestry/fork invariants are normative;
- [ ] EventRef ownership/serialization/persistence mapping is frozen;
- [ ] child Event ordering and ancestor visibility are explicit;
- [ ] Work clone/reset rules are explicit;
- [ ] focused contract tests pass;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned as M5 SERIAL ROOT after #66.
