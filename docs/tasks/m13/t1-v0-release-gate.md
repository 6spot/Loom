---
task: M13-T1
issue: 202
status: planned
depends_on: [152, 161, 167, 173, 181, 186, 192, 197, 201]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M13-T1 — Integrated Loom Engine V0 release gate

## End-to-end scenario
1. Clean PostgreSQL18+pgvector/blob + server R1 + neutral Capabilities/Templates.
2. Template-backed World birth; verify immutable Binding.
3. Direct Action + durable idempotent Ingress through root Sessions.
4. Event/State + Reaction Work commit; SSE/CLI observation.
5. Kill/restart before Work; prove logical-head scheduler/fencing/retry.
6. Explicit World-Time advancement, due quiescence and Chronology Budget.
7. State/History/trajectory/causal/catalog/semantic/blob reads; projection delete/rebuild authority test.
8. Replay current/history; historical fork; branch isolation/Binding inheritance/new Work IDs.
9. Activate R2; historical Sessions/Events remain R1, new Sessions R2.
10. Deterministic Agency Wake: NoAction, valid Act, semantic Rejected and CAS-conflict/resample.
11. Inspect Event→Session→Revision/executor/read/entropy/call provenance.
12. Full stop/restart and re-check World/Timeline/Binding/Event/State/logical Work/Ingress/provenance.
13. Representative workflows through CLI only.

## Final gates
- [ ] Architecture checker, fmt, check/all-targets/all-features, clippy -D warnings, workspace tests, rustdoc -D warnings.
- [ ] Dependency/security gate.
- [ ] PostgreSQL18+pgvector/blob integration.
- [ ] Property/fault + scheduler/replay/fork/provenance/Agency suites.
- [ ] Black-box server/HTTP/SSE/CLI tests.
- [ ] Capacity benchmark artifact/evidence present.

No direct DB/Runtime substitute, skipped restart/fork/revision/chronology/Agency edge cases, vendor-LLM requirement or partial/red completion evidence.

## Verification evidence
Pending.