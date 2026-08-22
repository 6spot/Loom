---
task: M5-T3
issue: 155
status: planned
depends_on: [153, 154]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M5-T3 — Bounded FailurePolicy and blocked observability

## Contract
- Bounded automatic technical attempts with Platform-Time backoff; retry keeps WorkId/due/order and changes only operational metadata.
- Exhaustion has an explicit authorized logical terminal exit (`Dead`) under v0 policy; operator may also authorize `Cancelled`/`Dead` through Runtime Control.
- Missing compatible implementation means execution did not start: no technical attempt consumed; Work stays Pending/head-blocking.
- Surface `TimelineBlockedOnMissingImplementation` with World/Timeline/Work, semantic requirement, active revision and useful observed metadata.
- Terminal Work cannot be resurrected; later retry is new Work with origin/provenance reference.

## Forbidden
No infinite retry, row deletion as terminalization, missing-software attempt consumption, or fake failure Events.

## Acceptance
- [ ] Retry is World/logical-state neutral.
- [ ] Bounded exhaustion/authorized terminalization is reconstructable.
- [ ] Missing implementation blocks and is observable.
- [ ] Restart + standard gates pass.

Architecture: Amendment 0001 §1; Amendment 0002 §5.

## Verification evidence
Pending.