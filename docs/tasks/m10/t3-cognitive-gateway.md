---
task: M10-T3
issue: 189
status: planned
depends_on: [183, 187, 188]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M10-T3 — CognitiveExecutor gateway

- Inject CognitiveExecutor through composition; providers live outside Runtime/Agency.
- Agency Wake Session pins compatible cognitive implementation/policy before context/executor call.
- Executor receives Agency values only, no Storage/BaseWorldView/Commit/network authority.
- Record provider/model/context ReadSet/entropy evidence into Session provenance.
- Deterministic fake supports Act/NoAction/technical error plus controllable delay for CAS tests.
- Technical failure differs from NoAction and enters bounded FailurePolicy.

## Acceptance
- [ ] Fake and production adapters share same SPI.
- [ ] Restricted context only.
- [ ] Provenance records executor/context evidence.
- [ ] NoAction/error are distinct; concurrent Sessions isolated.
- [ ] Standard gates pass.

## Verification evidence
Pending.