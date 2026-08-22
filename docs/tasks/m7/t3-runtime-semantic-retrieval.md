---
task: M7-T3
issue: 170
status: planned
depends_on: [169]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M7-T3 — Runtime-mediated semantic retrieval

- Capability/Agency request semantic evidence through approved host values, never PgPool/vector/provider clients.
- Runtime checks World Binding + projection availability under Session policy.
- Bound query/result/bytes/filter costs.
- ReadSet records index/query/projection/model revision and returned source references/order.
- Typed stale/unavailable behavior; never silently scan hidden World State as fallback.
- Replay/fork reconstruction issues zero semantic queries.

## Acceptance
- [ ] Host mediation/Binding/bounds are enforced.
- [ ] ReadSet evidence is deterministic.
- [ ] Stale/unavailable path is typed.
- [ ] Replay calls zero retrieval.
- [ ] InMemory/pgvector parity + standard gates pass.

## Verification evidence
Pending.