---
task: SCHD-T19
issue: 421
status: planned
depends_on: [417]
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T19 — Prove a Timeline forked after startup is auto-scheduled

## Goal

Prove that a child Timeline forked while the server is running is discovered
and progressed automatically, independently of World creation.

## Scope and acceptance

- [ ] Use a real LoomServer and controlled PostgreSQL 18 with no fixed target
      configuration; create/open the source through supported surfaces.
- [ ] Fork after startup through the formal Timeline API/client, ensure the
      child has representative Pending Work, and observe it through formal
      History/Facet/Admin reads without manual drive or ID injection.
- [ ] Verify parent/child branch isolation and stable required live execution.
- [ ] Do not alter fork/Work cloning semantics or substitute direct SQL,
      restart or the T18 World-create-only scenario.
