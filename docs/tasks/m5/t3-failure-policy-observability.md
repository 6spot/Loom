---
task: M5-T3
issue: 155
status: completed
depends_on: [153, 154]
created_at: 2026-08-22
started_at: 2026-08-23
completed_at: 2026-08-23
completion_pr: 218
merge_sha: 987b6a9bbc77d73d5dbd5a57eb41dd6f44564393
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
- [x] Retry is World/logical-state neutral.
- [x] Bounded exhaustion/authorized terminalization is reconstructable.
- [x] Missing implementation blocks and is observable.
- [x] Restart + standard gates pass.

Architecture: Amendment 0001 §1; Amendment 0002 §5.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.