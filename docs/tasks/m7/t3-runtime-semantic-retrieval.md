---
task: M7-T3
issue: 170
status: completed
depends_on: [169]
created_at: 2026-08-22
started_at: 2026-08-23
completed_at: 2026-08-23
completion_pr: 227
merge_sha: f3f1c3b3de1fe6b8a391e4cdbe5b42b351268364
---
# M7-T3 — Runtime-mediated semantic retrieval

- Capability/Agency request semantic evidence through approved host values, never PgPool/vector/provider clients.
- Runtime checks World Binding + projection availability under Session policy.
- Bound query/result/bytes/filter costs.
- ReadSet records index/query/projection/model revision and returned source references/order.
- Typed stale/unavailable behavior; never silently scan hidden World State as fallback.
- Replay/fork reconstruction issues zero semantic queries.

## Acceptance
- [x] Host mediation/Binding/bounds are enforced.
- [x] ReadSet evidence is deterministic.
- [x] Stale/unavailable path is typed.
- [x] Replay calls zero retrieval.
- [x] InMemory/pgvector parity + standard gates pass.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.