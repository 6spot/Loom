---
task: M7-T1
issue: 168
status: planned
depends_on: [167]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M7-T1 — Binding-aware Catalog and bounded history queries

- Distinguish Global Installed Catalog from World-Scoped Catalog (Binding + current compatible software).
- Expose generic semantic descriptors/schemas without resolver/handler objects.
- Add ancestry-aware Entity/Relationship trajectories and EventRef causes/effects/bounded causal traversal.
- Deterministic pagination/depth/result limits; no second graph authority.
- Do not introduce standalone `EventScope`/`ScopeTypeId` without an Amendment.

## Acceptance
- [ ] Global vs World catalog differs under two bindings.
- [ ] Trajectories/causality respect ancestry boundaries.
- [ ] Ordering/cursors are stable and bounded.
- [ ] Runtime/Storage internals do not leak.
- [ ] PostgreSQL/InMemory + standard gates pass.

## Verification evidence
Pending.