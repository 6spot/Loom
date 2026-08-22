---
task: M8-T5
issue: 93
status: planned
depends_on: [89]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M8-T5 — Immutable Object Store / Blob Foundation

## Goal
Provide immutable large-content storage with content integrity and stable references, isolated from World authority.

## Required implementation
- Implement BlobStore port ownership frozen in #89.
- Use immutable/content-addressed identity with BLAKE3 or contract-selected hash and integrity verification.
- Add deterministic in-memory/local test adapter and maintained S3-compatible adapter; credentials/config live in composition layer.
- Persist only required blob reference metadata (hash/size/content type/provenance) in PostgreSQL if contract requires it.
- Typed missing/corrupt/unavailable errors; World/Event carries stable BlobRef, not client handles/large bytes.

## Forbidden shortcuts
No S3 types in engine contracts, mutable overwrite under same ref, unchecked hashes or JSONB as fake blob store.

## Acceptance checklist
- [ ] immutable reference/integrity behavior is deterministic;
- [ ] corrupt/missing errors are typed;
- [ ] local and S3-compatible adapter contracts exist;
- [ ] secrets do not leak lower layers;
- [ ] replay works without downloading blob body;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned; parallel-safe after #89.
