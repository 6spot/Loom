---
task: SCHD-T13
issue: 415
status: planned
depends_on: [414]
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T13 — Wire SchedulerSupervisor into LoomServer build/run lifecycle

## Goal

Construct and run automatic Scheduler supervision as part of every successful
`loom-server` lifecycle without a configured Timeline target.

## Scope and acceptance

- [ ] Build the Supervisor Runtime from the same registry, clock, budgets,
      failure policy and storage authority as the existing Scheduler path.
- [ ] Construct it unconditionally, store it in `LoomServer`, and run it beside
      HTTP/Ingress under the shared shutdown signal; fatal errors request shared
      shutdown through existing patterns.
- [ ] Preserve PostgreSQL CAS/fence authority and one current-thread loop.
- [ ] Tests cover no-target startup, empty-store idle presence, fatal error
      propagation and coexistence of HTTP/Ingress/Supervisor.
- [ ] Do not remove the old worker, config/env, add a service/container or add
      a disable flag; later cleanup leaves own those changes.
