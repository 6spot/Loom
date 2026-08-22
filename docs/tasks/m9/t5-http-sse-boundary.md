---
task: M9-T5
issue: 100
status: planned
depends_on: [96, 98, 99]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M9-T5 — `loom-boundary` HTTP/JSON + SSE

## Goal
Implement transport mapping for unified Loom API while preserving `loom-boundary -> loom-api` only.

## Required implementation
- Add Axum/Tower and `loom-api`; architecture checker must reject Runtime/Storage/Capability imports.
- Map World, Timeline/fork, Action, Query, History/trajectory/causality, Catalog and Ingress endpoints.
- Map Subscription to SSE with cursor/Last-Event-ID semantics.
- Add request/response/SSE limits, typed error mapping and disconnect behavior.
- Test against fake/in-process `loom-api` services, not Runtime internals.

## Forbidden shortcuts
No Runtime/Storage imports, Capability-specific routes, SQL/registry calls in handlers or HTTP types leaking into API.

## Acceptance checklist
- [ ] dependency DAG stays compliant;
- [ ] API domains have documented HTTP mapping;
- [ ] typed errors map consistently;
- [ ] SSE resume/backpressure tests pass;
- [ ] fake-API transport tests pass;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after Ingress/feed contracts.
