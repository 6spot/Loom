---
task: M6-T1
issue: 162
status: planned
depends_on: [161]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M6-T1 — Pure World-State replay

- Apply authoritative ordered committed Events and frozen `WorldEffect`s only.
- Reconstruct Entity/Relationship/Facet materialization + Event head position.
- `occurred_at` is historical metadata; never derive Timeline World Time from it.
- Call no resolver/handler/Reaction/invariant-current-code/entropy/cognition/provider/clock.
- Fail typed on non-contiguous EventSeq or impossible frozen effects.

## Acceptance
- [ ] Every mechanical effect and same-Event structural case replays.
- [ ] Replayed head equals current materialized state.
- [ ] Changing current Capability implementations does not alter output.
- [ ] Replay makes zero execution/provider calls.
- [ ] Standard gates pass.

Architecture: `world-runtime.md` Replay + A0001 Event-time ownership.

## Verification evidence
Pending.