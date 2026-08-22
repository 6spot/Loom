---
task: M8-T1
issue: 174
status: planned
depends_on: [173]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M8-T1 — Ingress and Subscription API contracts

- Transport-neutral Ingress envelope: stable ID/idempotency, source/provenance, target, opaque auth policy context, source/platform metadata, ActionInvocation.
- Distinguish accepted/deduped, completed semantic result, semantic rejection and technical failure/retry.
- Change Feed cursor is committed Timeline history identity, not process notification identity.
- Define reconnect/resume/end/backpressure values without transport types.
- Keep Admin/Runtime Control separate from ordinary World API.

## Forbidden
No HTTP types in `loom-api`, direct Ingress Event/Effect/commit endpoint, accepted-as-World-truth, or subscriber authority.

## Acceptance
- [ ] Contracts serialize/document cleanly.
- [ ] Result/lifecycle states are unambiguous.
- [ ] Idempotency conflict + feed cursor/resume are explicit/bounded.
- [ ] API dependency DAG + standard gates pass.

Architecture: Amendment 0001 §6.2.

## Verification evidence
Pending.