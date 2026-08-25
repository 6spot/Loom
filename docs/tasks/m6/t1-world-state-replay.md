---
task: M6-T1
issue: 162
status: completed
depends_on: [161]
created_at: 2026-08-22
started_at: 2026-08-23
completed_at: 2026-08-23
completion_pr: 222
merge_sha: 3e26d097c39cba5d42a2c4b71251a4420899a5fc
---
# M6-T1 — Pure World-State replay

- Apply authoritative ordered committed Events and frozen `WorldEffect`s only.
- Reconstruct Entity/Relationship/Facet materialization + Event head position.
- `occurred_at` is historical metadata; never derive Timeline World Time from it.
- Call no resolver/handler/Reaction/invariant-current-code/entropy/cognition/provider/clock.
- Fail typed on non-contiguous EventSeq or impossible frozen effects.

## Acceptance
- [x] Every mechanical effect and same-Event structural case replays.
- [x] Replayed head equals current materialized state.
- [x] Changing current Capability implementations does not alter output.
- [x] Replay makes zero execution/provider calls.
- [x] Standard gates pass.

Architecture: `world-runtime.md` Replay + A0001 Event-time ownership.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.