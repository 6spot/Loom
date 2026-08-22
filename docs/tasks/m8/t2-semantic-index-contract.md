---
task: M8-T2
issue: 90
status: planned
depends_on: [89]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M8-T2 — SemanticIndex Contract and Discovery

## Goal
Let Capabilities declare semantic indexes and generic consumers discover them without storage/provider leakage.

## Required implementation
- Add Capability-owned index identity/definition with owner, source domain, stable vector/query metadata, description/revision.
- Register/validate deterministic duplicate/ownership/config errors.
- Extend Catalog with semantic index descriptors.
- Define Runtime query values (index, vector/query, limit/min-score/source filters) under #89.

## Forbidden shortcuts
No pgvector/SQL/provider SDK types in contracts, raw DB handles for Capability, index metadata as World State or per-Capability endpoint.

## Acceptance checklist
- [ ] registration/ownership passes;
- [ ] invalid/duplicate definitions fail deterministically;
- [ ] Catalog exposes metadata only;
- [ ] query values are documented/serializable as needed;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after #89.
