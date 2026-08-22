---
task: M7-T4
issue: 171
status: planned
depends_on: [167]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M7-T4 — Immutable Blob/Object Store

- Stable BlobId/BlobRef/metadata/content-hash values + correctly owned BlobStore port.
- Content-addressed/immutable identity with integrity verification.
- Deterministic local/in-memory adapter + selected S3-compatible/object-store adapter; secrets live in Application config.
- Event/Facet may store BlobRef, but replay reconstructs only the reference and never downloads bytes.
- Missing/corrupt object is typed access failure and cannot rewrite World history/state.

## Acceptance
- [ ] Integrity/hash mismatch is detected.
- [ ] Local/S3 adapter contract passes.
- [ ] Blob absence changes only blob-read result.
- [ ] No secrets/provider types leak lower layers.
- [ ] Standard gates pass.

## Verification evidence
Pending.