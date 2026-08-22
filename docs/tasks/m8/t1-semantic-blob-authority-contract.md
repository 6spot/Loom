---
task: M8-T1
issue: 89
status: planned
depends_on: [87]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M8-T1 — Semantic Projection and Blob Authority Contract

## Goal
Freeze projection/content authority boundaries before vector/object-store adapters are implemented.

## Implementation contract
- Event/State remain authority; embeddings/index rows are rebuildable projections.
- Define stable semantic source refs, projection/model revision metadata, Runtime query/result/read-dependency contracts and budgets.
- Define immutable BlobId/BlobRef/hash/metadata and BlobStore port ownership.
- Define how World values reference blobs without requiring blob availability for replay.
- Define rebuild/reindex and missing/stale/corrupt typed behavior.

## Forbidden shortcuts
No vector result as World truth, provider/storage SDK types in Core/Protocol/API, giant blob bytes in normal JSON State or replay dependency on vectors/blob bodies.

## Acceptance checklist
- [ ] projection vs authority rules are normative;
- [ ] semantic source/revision/query/result ownership is explicit;
- [ ] blob identity/hash semantics are explicit;
- [ ] replay/fork behavior under missing projection/blob is defined;
- [ ] contract tests/docs pass;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned as M8 SERIAL ROOT.
