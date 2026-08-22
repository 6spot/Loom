---
task: M8-T6
issue: 179
status: planned
depends_on: [178]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M8-T6 — Formal HTTP Loom API client

- Implement supported Loom API services over HTTP/JSON/SSE mapping.
- Preserve typed IDs/errors/cursors/Ingress/Subscription semantics.
- Configurable URL/auth/cancellation/timeouts; no hard-coded credentials.
- SSE reconnect/resume follows API contract.
- Do not automatically retry non-idempotent direct Actions; explicit Ingress idempotency may retry safely.
- Client/boundary compatibility tests prevent DTO/route drift.

## Acceptance
- [ ] All M8 public domains usable through client.
- [ ] No Runtime/Storage/Capability dependency.
- [ ] Typed behavior round-trips and standard gates pass.

## Verification evidence
Pending.