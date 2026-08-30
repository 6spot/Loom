---
task: VALR-T27
issue: 392
status: completed
depends_on: [320]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at: 2026-08-30
completion_pr: 393
merge_sha: 02c55a6b5c34f227abfcb732a21bf6c390e22578
architecture_decision_blocker: false
---

# VALR-T27 — Formal derived-resource public read boundary

## Completion record

T27 is complete. Architecture Amendment 0004 approved the minimal observation boundary required for CV-028 and CV-029, and PR #393 merged the implementation as `02c55a6b5c34f227abfcb732a21bf6c390e22578`.

The expansion is intentionally narrow:

- `QueryService::query_semantic_projection` is read-only and provider-neutral.
- `QueryService::read_blob` reads one exact immutable blob reference and verifies integrity.
- projection register/rebuild/delete remain Runtime/test-driver capabilities, not public mutation APIs.
- blob write/delete/list/browse remain outside the public query contract.
- no SQL, provider SDK, Storage handle, or alternate World authority crosses `loom-api`.

## Validation evidence

PR #393 exact-head CI run `33269628735` completed successfully after the CLI error-enum exhaustiveness fix.

The successful run included dependency/security policy, architecture policy, Validator authority governance, fmt, workspace check, strict Clippy, full repository-managed workspace tests, rustdoc with warnings denied, and the complete PostgreSQL 18 persistence-contract job.

`apps/loom-validator/tests/semantic_blob.rs` executed 11/11 tests successfully, including controlled InMemory and PostgreSQL 18 CV-028/CV-029 paths. Acceptance observations use `LoomClient`; Runtime/ProjectionStore/BlobStore operations are setup or fault drivers only.

## Acceptance

- [x] Amendment 0004 is indexed and governs the change.
- [x] Product API growth is limited to two read-only Query operations.
- [x] Runtime remains the sole gateway behind both reads.
- [x] CV-028 public observations prove derived delete/rebuild does not rewrite World truth.
- [x] CV-029 public observations distinguish success, not-found and integrity failure without rewriting World truth.
- [x] No projection/blob mutation authority is public.
- [x] Exact-head full Rust and PostgreSQL 18 CI is green.
- [x] PR #393 is merged and durable completion evidence is recorded.
