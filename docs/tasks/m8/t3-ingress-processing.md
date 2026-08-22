---
task: M8-T3
issue: 176
status: planned
depends_on: [150, 175]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
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
- [ ] Direct and Ingress Action semantics match.
- [ ] Semantic rejection deterministic.
- [ ] Crash-window has at most one World mutation.
- [ ] Restart/idempotency + standard gates pass.

## Verification evidence
Pending.