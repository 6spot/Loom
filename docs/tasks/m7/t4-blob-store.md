---
task: M7-T4
issue: 171
status: in_review
depends_on: [167]
created_at: 2026-08-22
started_at: 2026-08-23
completed_at: 2026-08-23
completion_pr: none (Executor constraint)
merge_sha: candidate SHA reported in issue handoff
---
# M7-T4 — Immutable Blob/Object Store

- Stable BlobId/BlobRef/metadata/content-hash values + correctly owned BlobStore port.
- Content-addressed/immutable identity with integrity verification.
- Deterministic local/in-memory adapter + selected S3-compatible/object-store adapter; secrets live in Application config.
- Event/Facet may store BlobRef, but replay reconstructs only the reference and never downloads bytes.
- Missing/corrupt object is typed access failure and cannot rewrite World history/state.

## Acceptance
- [x] Integrity/hash mismatch is detected.
- [x] Local/S3 adapter contract passes.
- [x] Blob absence changes only blob-read result.
- [x] No secrets/provider types leak lower layers.
- [x] Standard gates pass.

## Verification evidence
Runtime/Storage targeted tests, workspace check/clippy/test, architecture, format
and rustdoc gates pass. Blob tests cover deterministic BLAKE3 references,
immutable duplicate puts, local filesystem and S3-compatible object-store
adapters, corrupt-body hash/size mismatch, unavailable reads, and replay
materialization/head invariance after the referenced object is removed.
