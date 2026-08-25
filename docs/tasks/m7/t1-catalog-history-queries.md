---
task: M7-T1
issue: 168
status: completed
depends_on: [167]
created_at: 2026-08-22
started_at: 2026-08-23
completed_at: 2026-08-23
completion_pr: 227
merge_sha: f3f1c3b3de1fe6b8a391e4cdbe5b42b351268364
---
# M7-T1 — Binding-aware Catalog and bounded history queries

- Distinguish Global Installed Catalog from World-Scoped Catalog (Binding + current compatible software).
- Expose generic semantic descriptors/schemas without resolver/handler objects.
- Add ancestry-aware Entity/Relationship trajectories and EventRef causes/effects/bounded causal traversal.
- Deterministic pagination/depth/result limits; no second graph authority.
- Do not introduce standalone `EventScope`/`ScopeTypeId` without an Amendment.

## Acceptance
- [x] Global vs World catalog differs under two bindings.
- [x] Trajectories/causality respect ancestry boundaries.
- [x] Ordering/cursors are stable and bounded.
- [x] Runtime/Storage internals do not leak.
- [x] PostgreSQL/InMemory + standard gates pass.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.