---
task: M5-T1
issue: 153
status: planned
depends_on: [152]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M5-T1 — Durable Work logical target, due and order

## Contract
- Persist explicit target semantics: Capability Work vs Agency Wake.
- Persist non-null `effective_due_world_time`; Immediate resolves to scheduling commit World Time.
- Assign Timeline-local persistent `logical_schedule_order` in the scheduling Logical Commit.
- Retry/lease fields are operational only and cannot change target/due/order.
- Migrate old nullable `due_world_time` rows deterministically in InMemory/PostgreSQL.

## Forbidden
No UUID/row/platform-time tie breaker, logical `Running` state for leases, nullable semantic due, or fake WorkHandler for Agency Wake.

## Acceptance
- [ ] Same-instant order survives restart.
- [ ] Retry/lease never changes logical chronology.
- [ ] Target kind is explicit without payload convention.
- [ ] Migration + PostgreSQL/InMemory + standard gates pass.

Architecture: Amendment 0003 §§3.1–3.2; scheduler chronology baseline.

## Verification evidence
Pending.

## Progress Log
- 2026-08-22 — Planned.