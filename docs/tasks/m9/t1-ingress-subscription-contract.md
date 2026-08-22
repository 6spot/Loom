---
task: M9-T1
issue: 96
status: planned
depends_on: [94]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M9-T1 — Public Ingress and Subscription Contracts

## Goal
Freeze transport-neutral API contracts for durable external input and committed change subscription.

## Implementation contract
- Add focused Ingress/Subscription service domains to `loom-api` with no HTTP/storage/runtime types.
- Ingress carries idempotency identity, source metadata, World/Timeline target, ActionInvocation/payload and permitted source/auth metadata; Runtime records receipt platform time separately.
- Accepted/persisted is not World Truth; completed result links to normal Action outcome/EventRefs.
- Define idempotency scope and same-key/different-request conflict.
- Change Feed cursor is committed-history based and defines reconnect/resume/backpressure semantics.

## Forbidden shortcuts
No HTTP/SSE types in API, direct Event/Effect ingress, subscriber callback in commit or memory-only idempotency.

## Acceptance checklist
- [ ] contracts are transport-neutral/documented;
- [ ] idempotency/conflict semantics are explicit;
- [ ] accepted vs committed boundary is explicit;
- [ ] cursor/reconnect/backpressure is explicit;
- [ ] serialization/contract tests pass;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned as M9 SERIAL ROOT.
