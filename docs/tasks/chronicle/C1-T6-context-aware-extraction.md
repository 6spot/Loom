---
task: C1-T6
issue: 495
status: in_progress
depends_on: [C1-T5]
created_at: 2026-09-04
started_at: 2026-09-04
completed_at:
completion_pr:
merge_sha:
---

# Chronicle Context-Aware Chunk Extraction

## Canonical scope

GitHub Issue #495 is the executable specification.

## Goal

Extend C0 contract-first extraction to persisted book chunks with explicit context, bounded repair, exact evidence, and replayable model-attempt provenance.

## Acceptance

- [ ] schema-valid Entity/Event/Claim candidates are produced from persisted chunks.
- [ ] every Claim preserves exact evidence/source locator.
- [ ] model/prompt/contract/input-output attempt history is replayable.
- [ ] invalid output repairs are bounded and fail closed.
- [ ] inherited time/coreference cases pass without invented precision.
- [ ] resume/retry is idempotent at accepted chunk output.
- [ ] ContextState never becomes historical authority.
- [ ] C0 grounding/evaluator regressions remain green.
- [ ] Chronicle CI passes.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-04 — Implementation started: versioned chunk-extraction module (`persistence/extraction.py`: bounded request, mechanical validation, bounded correction, replayable ChunkRun history), worker real `extract` path (opt-in `chunk_model` hook, fake path default), inherited-context fixture, unit + PostgreSQL extract suites. Delivery PR pending; post-merge reconciliation (completed/completion_pr/merge_sha) pending.
