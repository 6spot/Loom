---
task: M4-T1
issue: 146
status: completed
depends_on: []
created_at: 2026-08-22
started_at: 2026-08-22
completed_at: 2026-08-22
completion_pr: 205
merge_sha: fe535892c5f6ba9abff1447d990f719b4e89161c
---

# M4-T1 — Event occurrence authority and explicit World Time

## Goal

Remove the two legacy assumptions superseded by Amendment 0001 §5: Capability-selected authoritative `occurred_at` and Event-driven World-Time advancement.

## Implementation contract

- Remove authoritative `occurred_at` from `ProposedEvent`; source/effective timestamps may remain domain payload metadata.
- Runtime stamps committed Event occurrence time from the Session-pinned Timeline `WorldInstant`.
- Ordinary Event commit must never advance `Timeline.world_time`.
- Add/complete Runtime-owned `AdvanceWorldTime(current -> next)` with monotonic validation and expected `TimelineVersion` CAS.
- Persist/read Event occurrence time and Timeline World Time independently in InMemory and PostgreSQL.
- Update M1–M3 fixtures without weakening semantic tests.

## Forbidden shortcuts

No Capability-controlled default timestamp, DB `NOW()` as World Time, synthetic time Event, or automatic Event-driven time advance.

## Acceptance

- [x] Event occurrence equals pinned World Time.
- [x] Event commit does not move World Time.
- [x] Explicit stale-CAS time transition loses atomically.
- [x] Platform retry/lease/clock operations never alter World Time.
- [x] Architecture/fmt/check/clippy/tests/rustdoc + PostgreSQL parity pass.

Architecture basis: Architecture Index supersession rows for Event occurrence time; Amendment 0001 §5.

## Verification evidence

- PR #205 merged as `fe535892c5f6ba9abff1447d990f719b4e89161c`.
- Post-merge CI run `32566321119` passed the Rust and PostgreSQL 18 jobs.
- Reconciliation rerun: `postgres_commit`, `postgres_vertical`, `postgres_restart_resume`, and the neutral template gate all pass against PostgreSQL 18 or InMemory authority as applicable.

## Progress Log

- 2026-08-22 — Planned during post-Amendment V0 replan.
- 2026-08-22 — Accepted and merged as PR #205; post-merge CI run `32566321119` passed.
