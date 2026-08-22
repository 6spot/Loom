---
task: M11-T3
issue: 115
status: planned
depends_on: [113, 114]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M11-T3 — Execution Session / Runtime Revision Binding

## Goal
Give every root Action/Work/Ingress execution a durable session pinned to one active Runtime Revision.

## Required implementation
- Runtime-owned session port + PostgreSQL/InMemory persistence for id, origin, target, pinned revision, start/end/status and root refs.
- Begin session before semantic/entropy/read work and capture active revision once.
- Use explicit origins for direct Action, Work and Ingress.
- Recover/mark crashed sessions under #113 without rebinding revision.
- Keep concurrent session provenance isolated.

## Forbidden shortcuts
No mid-session active revision lookup/switch, process-global mutable session, logs-only session identity or World Event for session lifecycle.

## Acceptance checklist
- [ ] each root path has one durable session;
- [ ] subresolution/commit stay on pinned revision;
- [ ] concurrent sessions isolate state;
- [ ] crash lifecycle survives restart;
- [ ] adapter/PostgreSQL parity passes;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after revision ledger.
