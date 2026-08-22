---
task: M7-T5
issue: 86
status: planned
depends_on: [83, 85]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M7-T5 — Runtime Worker Step and Resumable Scheduler Loop

## Goal
Execute due Durable Work through the existing Runtime authority path with bounded concurrency, retry policy and clean shutdown.

## Required implementation
- Add focused one-step worker operation: claim-next then existing WorkHandler → Resolution → validation → atomic commit/retry.
- Define lease/retry/backoff, idle polling, concurrency and shutdown policy.
- Keep long-running process loop in application/runtime orchestration, not Core semantics.
- Process death after claim is recoverable via lease expiry/fencing.
- PlatformClock controls operational timing only; World Time comes from Timeline snapshot.

## Forbidden shortcuts
No direct handler bypass, unbounded spawning, sleeping with transaction/Timeline lock, platform clock advancing World Time or swallowed retry persistence failures.

## Acceptance checklist
- [ ] one-step worker executes eligible Work end-to-end;
- [ ] idle path is typed/cheap;
- [ ] crash/lease-expiry/reclaim passes;
- [ ] bounded concurrency prevents duplicate completion;
- [ ] graceful shutdown behavior is tested;
- [ ] reaction Work resumes after restart.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after #85.
