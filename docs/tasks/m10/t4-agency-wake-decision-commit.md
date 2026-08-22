---
task: M10-T4
issue: 190
status: planned
depends_on: [156, 189]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M10-T4 — Atomic Agency Wake Decision/Action commit

- Scheduler `AgencyWake` admission resolves Agency/cognition target, never Capability WorkHandler.
- Build context/run cognition outside DB authority transaction, then interpret Decision under same pinned Session.
- `Act` re-enters ordinary World Binding + Action schema/resolver/subresolution/validation path; Agent origin is provenance, not hidden input.
- Optional Action Events/Effects + current Wake `Pending->Completed` + chronology consumption commit atomically under one version/fence.
- `NoAction` completes Wake with no World Event/State mutation.
- **V0 R-1:** semantic `Rejected` Act MUST complete current Wake as determined no-world-change. A later reconsideration schedules a new Wake; the rejected head cannot remain Pending.
- Technical cognition/runtime failure does not complete Wake and uses bounded FailurePolicy.

## Acceptance
- [ ] Act uses normal Action authority.
- [ ] Action+Wake completion+budget are atomic.
- [ ] NoAction and semantic Rejected complete without fake Events.
- [ ] Rejected Wake cannot head-block forever.
- [ ] Technical failure remains Pending/retriable; stale CAS/fence cannot partially commit.
- [ ] PostgreSQL/InMemory + standard gates pass.

Architecture: A0003 §§3.2/3.5; R-1 V0 policy fixed by this replan.

## Verification evidence
Pending.