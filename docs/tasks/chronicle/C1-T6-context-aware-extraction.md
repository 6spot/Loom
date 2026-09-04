---
task: C1-T6
issue: 495
status: completed
depends_on: [C1-T5]
created_at: 2026-09-04
started_at: 2026-09-04
completed_at: 2026-09-04
completion_pr: 516
merge_sha: 43249e4b248238632a0c80a187bf4d4a5d6136cf
---

# Chronicle Context-Aware Chunk Extraction

## Canonical scope

GitHub Issue #495 is the executable specification.

## Goal

Extend C0 contract-first extraction to persisted book chunks with explicit context, bounded repair, exact evidence, and replayable model-attempt provenance.

## Acceptance

- [x] schema-valid Entity/Event/Claim candidates are produced from persisted chunks.
- [x] every Claim preserves exact evidence/source locator.
- [x] model/prompt/contract/input-output attempt history is replayable.
- [x] invalid output repairs are bounded and fail closed.
- [x] inherited time/coreference cases pass without invented precision.
- [x] resume/retry is idempotent at accepted chunk output.
- [x] ContextState never becomes historical authority.
- [x] C0 grounding/evaluator regressions remain green.
- [x] Chronicle CI passes.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-04 — Implementation added context-aware per-chunk extraction over the C0 contract, exact evidence locators, bounded repair, append-only ChunkRun model-attempt history, replay verification, inherited-time handling, and opt-in worker model execution with fake path preserved.
- 2026-09-04 — Review remediation bound crash-window adoption to already accepted runs and required the staged-bundle JSON Schema to fail closed before real extraction; final local evidence covered persistence, worker PostgreSQL, C0 prototype/evaluator and read API suites.
- 2026-09-04 — Delivery PR #516 merged as `43249e4b248238632a0c80a187bf4d4a5d6136cf`. Exact delivery head `a5410683d6109bb9ff736ed6c87533720d765faa` passed GitHub Actions Chronicle run 33872373297 and Chronicle Docker run 33872373262. Catch-up post-merge reconciliation records the already-delivered task as completed on the canonical ledger.
