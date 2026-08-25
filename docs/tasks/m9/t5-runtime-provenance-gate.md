---
task: M9-T5
issue: 186
status: completed
depends_on: [182, 183, 184, 185]
created_at: 2026-08-22
started_at: 2026-08-24
completed_at: 2026-08-24
completion_pr: 241
merge_sha: 46fb9d348327ec62ec055f9749920c55ebccc30b
---
# M9-T5 — Runtime upgrade/provenance/control gate

Run Action/Work/Ingress under R1, capture evidence, start long R1 Session, activate compatible R2, finish R1 and run R2 Sessions. Restart; query Event↔Session↔Revision; exercise missing-implementation diagnostics and authorized terminalization/time controls; reject incompatible activation.

## Assertions
- [x] Historical Sessions/Events keep exact R1 assembly.
- [x] New Sessions pin R2; no running Session switches.
- [x] Activation/control history survives restart and creates no fake World Event.
- [x] Every Event has one Session; logical/no-change/rejected/failed Sessions remain auditable.
- [x] Admin controls use CAS/journal/quiescence, not DB bypass.
- [x] Public provenance contains no secrets.
- [x] Architecture/fmt/check/clippy/tests/rustdoc + PostgreSQL/server provenance suites pass.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.