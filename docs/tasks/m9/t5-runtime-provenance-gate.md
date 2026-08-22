---
task: M9-T5
issue: 186
status: planned
depends_on: [182, 183, 184, 185]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M9-T5 — Runtime upgrade/provenance/control gate

Run Action/Work/Ingress under R1, capture evidence, start long R1 Session, activate compatible R2, finish R1 and run R2 Sessions. Restart; query Event↔Session↔Revision; exercise missing-implementation diagnostics and authorized terminalization/time controls; reject incompatible activation.

## Assertions
- [ ] Historical Sessions/Events keep exact R1 assembly.
- [ ] New Sessions pin R2; no running Session switches.
- [ ] Activation/control history survives restart and creates no fake World Event.
- [ ] Every Event has one Session; logical/no-change/rejected/failed Sessions remain auditable.
- [ ] Admin controls use CAS/journal/quiescence, not DB bypass.
- [ ] Public provenance contains no secrets.
- [ ] Architecture/fmt/check/clippy/tests/rustdoc + PostgreSQL/server provenance suites pass.

## Verification evidence
Pending.