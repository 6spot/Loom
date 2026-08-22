---
task: M9-T7
issue: 102
status: planned
depends_on: [86, 93, 98, 100]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M9-T7 — `apps/loom-server` Composition Root

## Goal
Create the runnable Loom composition root that assembles concrete storage/adapters into Runtime and serves the unified API.

## Required implementation
- Add workspace app with governance-allowed dependencies.
- Wire PostgreSQL/migrations, PgStorage, registry, Runtime, Clock, identity, Entropy, Boundary, Durable Work worker and Ingress recovery worker; configure blob adapter as needed.
- Structured env/config, secret-safe diagnostics, tracing and graceful shutdown.
- Validate registry/persistence dependencies before accepting traffic.
- After composition, public behavior remains through Loom API/boundary.

## Forbidden shortcuts
No duplicate server handlers, Runtime→PgStorage dependency, hard-coded secrets or unbounded worker loops.

## Acceptance checklist
- [ ] server starts against PostgreSQL 18 config;
- [ ] migrations/registry validate before serving;
- [ ] boundary and workers share assembled authority safely;
- [ ] graceful shutdown works;
- [ ] restart reuses World/Work/Ingress persistence;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned as first real Loom application composition root.
