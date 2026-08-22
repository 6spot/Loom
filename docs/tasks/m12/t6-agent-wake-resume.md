---
task: M12-T6
issue: 126
status: planned
depends_on: [86, 121, 124, 125]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M12-T6 — Resumable Agent Wake

## Goal
Schedule autonomous cognition as Durable Work so wake obligations survive restart/fork and keep fencing/provenance semantics.

## Required implementation
- Use wake representation frozen in #121 on existing Durable Work/scheduler, not a second queue.
- Persist target Agent/World/Timeline + cognition policy/context request as stable future data.
- Schedule/cancel/clone follows M4 logical Work + M5 fork rules: new child WorkId, preserved semantic obligation, reset technical metadata.
- Claimed wake invokes cognitive gateway then Decision routing.
- Crash/retry/fencing prevents duplicate committed Agent action and provenance links wake→cognition→optional Action/Event.

## Forbidden shortcuts
No in-memory timer authority, separate Agent scheduler DB, background cognition without Work claim or copied retry state across fork.

## Acceptance checklist
- [ ] wake survives restart;
- [ ] due wake claims once and invokes cognition;
- [ ] stale fencing cannot duplicate mutation;
- [ ] fork clones wake with new ID/branch-local future;
- [ ] logical wake history reconstructs;
- [ ] provenance chain passes.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after scheduler/cognition routing.
