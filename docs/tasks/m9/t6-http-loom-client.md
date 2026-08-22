---
task: M9-T6
issue: 101
status: planned
depends_on: [100]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M9-T6 — Formal HTTP Loom API Client

## Goal
Provide a reusable typed HTTP client so CLI/Studio consume Loom without Runtime/Storage imports or hand-rolled endpoint DTOs.

## Required implementation
- Add client adapter in an architecture-approved layer; update governance/checks first if a new crate edge is needed.
- Implement supported `loom-api` service contracts over M9 HTTP/SSE mapping.
- Preserve typed errors, DTOs, pagination/cursors and SSE resume semantics.
- Configurable base URL/timeouts/cancellation; auth remains app/config concern.
- Contract tests detect boundary/client drift.

## Forbidden shortcuts
No Runtime/Storage/Capability dependency, shadow DTO protocol, hard-coded URL/credentials or unsafe retries of non-idempotent Action.

## Acceptance checklist
- [ ] all M9 client domains are covered;
- [ ] typed errors/pagination/cursors work;
- [ ] SSE reconnect passes;
- [ ] boundary/client compatibility tests pass;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after #100.
