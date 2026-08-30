---
task: SCHD-T17
issue: 419
status: planned
depends_on: [418]
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T17 — Rewrite quickstart/operator guidance for automatic Scheduler discovery

## Goal

Align active user/operator documentation with one-command deployment and
automatic discovery.

## Scope and acceptance

- [ ] Update Scheduler/deployment sections in `docs/quickstart.md`,
      `docs/operator-guide.md` and only directly relevant active `README.md`
      prose.
- [ ] Describe `docker compose up -d`, server-lifecycle supervision and
      automatic discovery of new/forked Timelines with Pending Work.
- [ ] State that PostgreSQL remains authority and Supervisor discovery does not
      choose logical Work ordering; retain accurate blocked Work, Chronology
      Budget and Runtime Revision semantics.
- [ ] Remove instructions to set target IDs or force-recreate for activation;
      document only existing poll/limit tuning.
- [ ] Documentation links/checks and CI pass; no speculative bus, pool,
      bootstrap or multi-instance tutorial is added.
