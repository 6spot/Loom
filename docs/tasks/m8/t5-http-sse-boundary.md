---
task: M8-T5
issue: 178
status: completed
depends_on: [174, 176, 177]
created_at: 2026-08-22
started_at: 2026-08-24
completed_at: 2026-08-24
completion_pr: 234
merge_sha: 50bbddfac9bc52cf7281c02f223b4f13fa8b5ff9
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
- [x] Architecture checker proves `loom-boundary -> loom-api` isolation.
- [x] Error/cursor/SSE reconnect/limits tests pass.
- [x] Standard gates pass.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.