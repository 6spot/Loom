---
task: M10-T3
issue: 189
status: completed
depends_on: [183, 187, 188]
created_at: 2026-08-22
started_at: 2026-08-24
completed_at: 2026-08-24
completion_pr: 244
merge_sha: 6baf52841996bef79957a97badf6caaa06029187
---
# M10-T3 — CognitiveExecutor gateway

- Inject CognitiveExecutor through composition; providers live outside Runtime/Agency.
- Agency Wake Session pins compatible cognitive implementation/policy before context/executor call.
- Executor receives Agency values only, no Storage/BaseWorldView/Commit/network authority.
- Record provider/model/context ReadSet/entropy evidence into Session provenance.
- Deterministic fake supports Act/NoAction/technical error plus controllable delay for CAS tests.
- Technical failure differs from NoAction and enters bounded FailurePolicy.

## Acceptance
- [x] Fake and production adapters share same SPI.
- [x] Restricted context only.
- [x] Provenance records executor/context evidence.
- [x] NoAction/error are distinct; concurrent Sessions isolated.
- [x] Standard gates pass.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.