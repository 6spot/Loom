---
task: SCHD-T12
issue: 414
status: planned
depends_on: [413]
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T12 — Implement Supervisor polling loop + graceful shutdown

## Goal

Turn bounded Supervisor cycles into the long-running application loop using the
existing worker poll interval and shutdown contract.

## Scope and acceptance

- [ ] Repeatedly run the T10/T11 cycle until shutdown, checking shutdown before
      each new cycle and sleeping only between cycles.
- [ ] Reuse `worker_poll_interval`; platform sleep never advances World Time.
- [ ] Let an active drive finish, propagate genuine discovery/Runtime errors,
      and keep normal Blocked/Idle outcomes non-fatal.
- [ ] Async tests cover pre-start shutdown, one-cycle shutdown, empty/idle
      continuation and genuine errors.
- [ ] No server wiring, new config, notification optimization or worker pool is
      introduced.
