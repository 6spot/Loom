---
task: M4-T7
issue: 152
status: planned
depends_on: [146, 147, 148, 149, 150, 151]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M4-T7 — Reconciliation final gate

## Goal

Revalidate the real M1–M3 assets under the current architecture and establish the only supported baseline for M5+.

## Required scenario

- Fresh PostgreSQL 18 migration including Binding/Revision/Session additions.
- Register neutral Capabilities + Runtime Revision R1 and create a Template-backed World.
- Exercise success/rejection/no-change and cross-Capability subresolution through pinned Session/Assembly.
- Verify Runtime-stamped Event time and no implicit World-Time advancement.
- Restart and continue the World.
- Activate compatible R2 and prove old Session remains R1, next Session uses R2.
- Try incompatible assembly and prove execution unavailable while World/Binding/history remain unchanged.

## Final gates

- [ ] Architecture checker.
- [ ] fmt/check/clippy `-D warnings`/workspace tests/rustdoc `-D warnings`.
- [ ] PostgreSQL schema/read/commit/CAS/Work/restart suites.
- [ ] Every M4 task record/evidence is complete and agrees with its Issue.

## Verification evidence

Pending.

## Progress Log

- 2026-08-22 — Planned.