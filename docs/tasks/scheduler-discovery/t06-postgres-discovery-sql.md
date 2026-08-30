---
task: SCHD-T06
issue: 408
status: planned
depends_on: [405]
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T06 — Add PostgreSQL SQL for bounded pending-Timeline discovery

## Goal

Add the repository-owned PostgreSQL query required by T03 without wiring it to
`PgStorage` yet.

## Scope and acceptance

- [ ] Add SQL under the correct `crates/loom-storage/sql/` ownership domain.
- [ ] Return distinct owning `WorldId`/`TimelineId` targets with Pending Work.
- [ ] Implement the T03 deterministic order, cursor and positive `LIMIT`.
- [ ] Keep future-World-Time Pending Work visible and do not inspect lease,
      retry, handler, budget or worker identity.
- [ ] Use existing tables/columns, with no speculative migration/index or
      `FOR UPDATE`/`SKIP LOCKED`/claim statement.
- [ ] SQL ownership/static checks pass and the task evidence explains any
      schema decision.
