---
task: M8-T5
issue: 178
status: planned
depends_on: [174, 176, 177]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M8-T5 — `loom-boundary` HTTP/JSON + SSE

- Axum/Tower only at Boundary/Application layers.
- Generic routes map World/Template/Timeline/Action/Query/History/Catalog/Ingress public contracts; no Capability-specific endpoints.
- SSE maps Change Feed cursor/resume semantics.
- Typed API error→HTTP mapping hides SQL/Runtime authority internals.
- Bound request/response/header/SSE buffers and disconnects.
- Boundary tests depend only on fake/formal `loom-api` implementation.

## Forbidden
No Runtime/Storage/concrete Capability/PgPool import, direct resolver/DB call, shadow DTO protocol, or subscriber commit authority.

## Acceptance
- [ ] Architecture checker proves `loom-boundary -> loom-api` isolation.
- [ ] Error/cursor/SSE reconnect/limits tests pass.
- [ ] Standard gates pass.

## Verification evidence
Pending.