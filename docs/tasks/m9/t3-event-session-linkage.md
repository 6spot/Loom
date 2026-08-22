---
task: M9-T3
issue: 184
status: planned
depends_on: [183]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M9-T3 — Atomic Event ↔ Session linkage

- World Event commit and Session→EventRef provenance linkage share required transaction/linearization guarantee.
- Link only fixed Event IDs produced/validated by current Session.
- Apply uniformly to Action/Work/Reaction/Ingress/bootstrap/later Agency.
- Logical-only/no-change/rejected/failed Sessions finalize with zero fake Event refs.
- Crash recovery cannot leave a permanently committed Event orphaned from required Session evidence.
- Query EventRef→Session and Session→ordered EventRefs.

## Forbidden
No best-effort async link, Session ID in payload, causal-link reuse, or Storage-generated Session.

## Acceptance
- [ ] Exactly one producing Session per committed Event.
- [ ] Forced rollback/crash cannot orphan links.
- [ ] Restart parity + standard gates pass.

## Verification evidence
Pending.