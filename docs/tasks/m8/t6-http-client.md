---
task: M8-T6
issue: 179
status: completed
depends_on: [178]
created_at: 2026-08-22
started_at: 2026-08-24
completed_at: 2026-08-24
completion_pr: 235
merge_sha: ccaab83fd03d0aed3e8be8697a3cef9bece975ad
---
# M8-T6 — Formal HTTP Loom API client

- Implement supported Loom API services over HTTP/JSON/SSE mapping.
- Preserve typed IDs/errors/cursors/Ingress/Subscription semantics.
- Configurable URL/auth/cancellation/timeouts; no hard-coded credentials.
- SSE reconnect/resume follows API contract.
- Do not automatically retry non-idempotent direct Actions; explicit Ingress idempotency may retry safely.
- Client/boundary compatibility tests prevent DTO/route drift.

## Acceptance
- [x] All M8 public domains usable through client.
- [x] No Runtime/Storage/Capability dependency.
- [x] Typed behavior round-trips and standard gates pass.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.