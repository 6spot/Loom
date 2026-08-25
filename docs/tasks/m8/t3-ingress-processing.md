---
task: M8-T3
issue: 176
status: completed
depends_on: [150, 175]
created_at: 2026-08-22
started_at: 2026-08-24
completed_at: 2026-08-24
completion_pr: 232
merge_sha: 015294f828ca6cdde8038094505d3880f3040d6b
---
# M8-T3 — Ingress processing through normal authority

- Load/claim accepted Ingress, establish root Session with `ExecutionOrigin::Ingress`, then run exact Binding + Action schema/resolver/subresolution/validation/commit path.
- Success records Session/Event/result refs in Ingress state.
- Semantic Rejection completes; technical failure uses bounded operational retry.
- Recover World-commit/Ingress-finalization crash ambiguity using Session/Event/idempotency evidence, never blind rerun.
- Missing/incompatible implementation uses normal root execution semantics.

## Forbidden
No Ingress→CommitStore, special resolver hierarchy, raw ValidatedResolution creation, semantic-rejection retry, or duplicate crash-window commit.

## Acceptance
- [x] Direct and Ingress Action semantics match.
- [x] Semantic rejection deterministic.
- [x] Crash-window has at most one World mutation.
- [x] Restart/idempotency + standard gates pass.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.