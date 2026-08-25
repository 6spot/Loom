---
task: M12-T4
issue: 201
status: completed
depends_on: [198, 199, 200]
created_at: 2026-08-22
started_at: 2026-08-25
completed_at: 2026-08-25
completion_pr: 282
merge_sha: 52905862f3c26a6fb4d9991da2aa9fe8cfd11bc2
---
# M12-T4 — Public-consumer rehearsal gate

Follow the documented quickstart from a clean environment: server/dependencies, catalogs/Templates, World create, Action/rejection, State/History/trajectory/causality, Ingress, feed resume, Scheduler/World Time, replay/fork, Revision/provenance, deterministic Agency Wake and restart. Repeat key flows with CLI JSON.

## Assertions
- [x] Docs require no Runtime/Storage/DB bypass.
- [x] Commands/config match Linux-supported system.
- [x] Examples require no vendor secrets.
- [x] Architecture/deferred/capacity statements match implementation evidence.
- [x] Every stale/broken command/link found by rehearsal is fixed.
- [x] Docs/CLI/example tests are green.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.