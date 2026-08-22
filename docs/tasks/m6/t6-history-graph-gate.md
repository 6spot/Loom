---
task: M6-T6
issue: 80
status: planned
depends_on: [75, 76, 77, 78, 79]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M6-T6 — History / Trajectory / Causality Parity Gate

## Goal
Prove the full history query surface is complete, ancestry-correct and bounded without a second history authority.

## Required verification
Use parent/child/grandchild Timelines with scoped Events, participants, Relationship refs and branched causal DAGs. Verify full Catalog, Scope filter/round-trip, trajectories, EventRef lookup and direct/recursive causes/effects across InMemory/PostgreSQL after restart.

## Acceptance checklist
- [ ] full Catalog covers registered semantics;
- [ ] Scope validation/filtering passes;
- [ ] trajectories obey fork visibility;
- [ ] causal graph obeys ancestry and budgets;
- [ ] query operations do not mutate World/Runtime authority;
- [ ] restart and adapter parity pass;
- [ ] final architecture/fmt/check/clippy/tests/rustdoc/PostgreSQL candidate is green.

## Completion evidence
- PR:
- merge SHA:
- final candidate / CI:

## Progress log
- 2026-08-22 — Planned as M6 SERIAL GATE.
