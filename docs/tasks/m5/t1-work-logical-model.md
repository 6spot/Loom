---
task: M5-T1
issue: 153
status: completed
depends_on: [152]
created_at: 2026-08-22
started_at: 2026-08-23
completed_at: 2026-08-23
completion_pr: 216
merge_sha: 587672c63cb13f4808d14495054b67b5a0e3a799
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
- [x] Same-instant order survives restart.
- [x] Retry/lease never changes logical chronology.
- [x] Target kind is explicit without payload convention.
- [x] Migration + PostgreSQL/InMemory + standard gates pass.

Architecture: Amendment 0003 §§3.1–3.2; scheduler chronology baseline.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.

## Progress Log
- 2026-08-22 — Planned.