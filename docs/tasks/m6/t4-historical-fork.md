---
task: M6-T4
issue: 165
status: completed
depends_on: [163, 164]
created_at: 2026-08-22
started_at: 2026-08-23
completed_at: 2026-08-23
completion_pr: 225
merge_sha: 07525f68a06cffa418e988a8f324848c8dee301c
---
# M6-T4 — Historical fork

- Fork from optional exact committed TimelineVersion; head is convenience default.
- Reconstruct semantic State + World Time + logical Pending Work/order + chronology budget through replay only.
- Atomically persist child ancestry/materialization/future.
- New Work IDs; no operational retry/lease inheritance.
- Invalid/beyond-head/non-visible target leaves zero child artifacts.
- Parent future commits cannot rewrite child.

## Acceptance
- [x] Initial/early/mid/head fork fixtures are exact.
- [x] Historically Pending-only Work is cloned.
- [x] Budget position inherited, branch future diverges.
- [x] Agency Wake target clones correctly.
- [x] PostgreSQL/InMemory restart parity + standard gates pass.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.