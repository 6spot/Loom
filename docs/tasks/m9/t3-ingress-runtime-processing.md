---
task: M9-T3
issue: 98
status: planned
depends_on: [97]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M9-T3 — Ingress Processing Through Normal Action Authority

## Goal
Process accepted Ingress through the existing Action → Capability → Runtime validation → commit path.

## Required implementation
- Claim/reload accepted ingress and reconstruct its normal Action request.
- Persist outcome/EventRefs idempotently and close the crash window after World commit but before ingress status finalization.
- Detect already-completed execution using durable identifiers/provenance rather than rerunning blindly.
- Technical failures are retryable platform state; semantic rejection is a completed outcome.

## Forbidden shortcuts
No Ingress→CommitStore direct path, ingress-built `ValidatedResolution`, endless retry of semantic rejection or duplicate commit after ambiguous crash.

## Acceptance checklist
- [ ] execution uses existing Action authority;
- [ ] success/rejection results persist idempotently;
- [ ] technical failure recovery is safe;
- [ ] commit/status crash window cannot duplicate World mutation;
- [ ] InMemory/PostgreSQL/restart parity passes;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after durable ingress storage.
