---
task: M6-T4
issue: 165
status: planned
depends_on: [163, 164]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M6-T4 — Historical fork

- Fork from optional exact committed TimelineVersion; head is convenience default.
- Reconstruct semantic State + World Time + logical Pending Work/order + chronology budget through replay only.
- Atomically persist child ancestry/materialization/future.
- New Work IDs; no operational retry/lease inheritance.
- Invalid/beyond-head/non-visible target leaves zero child artifacts.
- Parent future commits cannot rewrite child.

## Acceptance
- [ ] Initial/early/mid/head fork fixtures are exact.
- [ ] Historically Pending-only Work is cloned.
- [ ] Budget position inherited, branch future diverges.
- [ ] Agency Wake target clones correctly.
- [ ] PostgreSQL/InMemory restart parity + standard gates pass.

## Verification evidence
Pending.