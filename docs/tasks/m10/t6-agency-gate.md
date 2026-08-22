---
task: M10-T6
issue: 192
status: planned
depends_on: [187, 188, 189, 190, 191]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M10-T6 — Agency final gate

Create a World with visible/hidden data and multiple same-WorldInstant Wakes. Test NoAction, valid Act, semantic Rejected, technical failure and delayed CAS loss; restart before/after claims; fork Pending Wakes; switch compatible Runtime/cognitive revision; inspect provenance.

## Assertions
- [ ] Hidden authoritative data is inaccessible.
- [ ] Wake obeys logical head/due/order/chronology and restart/fork.
- [ ] NoAction + semantic Rejected complete Wake without fake Events; rejection cannot block forever.
- [ ] Act uses normal Action authority.
- [ ] Technical failure bounded; missing cognitive software consumes no attempt.
- [ ] CAS has one logical winner and explicit reuse/resample evidence.
- [ ] Event→Session→revision/executor/context provenance survives restart.
- [ ] Same-instant Wake execution demonstrates Timeline serialization, not arbitrary write parallelism.
- [ ] Standard + PostgreSQL/server Agency gates pass.

## Verification evidence
Pending.