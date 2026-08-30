---
task: SCHD-T06
issue: 408
status: completed
depends_on: [405]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at: 2026-08-30
completion_pr: 440
merge_sha: 1d2c45fbd9b754034f8f275851a486e9612e6a21
---

# SCHD-T06 — Add PostgreSQL SQL for bounded pending-Timeline discovery

## Goal

Add the repository-owned PostgreSQL query required by T03 without wiring it to
`PgStorage` yet.

## Scope and acceptance

- [x] Add SQL under the correct `crates/loom-storage/sql/` ownership domain.
- [x] Return distinct owning `WorldId`/`TimelineId` targets with Pending Work.
- [x] Implement the T03 deterministic order, cursor and positive `LIMIT`.
- [x] Keep future-World-Time Pending Work visible and do not inspect lease,
      retry, handler, budget or worker identity.
- [x] Use existing tables/columns, with no speculative migration/index or
      `FOR UPDATE`/`SKIP LOCKED`/claim statement.
- [x] SQL ownership/static checks pass and the task evidence explains any
      schema decision.

## Completion evidence

- Delivery PR #440 merged on 2026-08-30 as
  `1d2c45fbd9b754034f8f275851a486e9612e6a21`.
