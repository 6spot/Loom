---
task: M4-T1
issue: 146
status: planned
depends_on: []
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
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

- [ ] Event occurrence equals pinned World Time.
- [ ] Event commit does not move World Time.
- [ ] Explicit stale-CAS time transition loses atomically.
- [ ] Platform retry/lease/clock operations never alter World Time.
- [ ] Architecture/fmt/check/clippy/tests/rustdoc + PostgreSQL parity pass.

Architecture basis: Architecture Index supersession rows for Event occurrence time; Amendment 0001 §5.

## Verification evidence

Record PR, merge SHA and CI/test runs here on completion.

## Progress Log

- 2026-08-22 — Planned during post-Amendment V0 replan.