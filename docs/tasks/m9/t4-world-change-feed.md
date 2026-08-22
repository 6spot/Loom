---
task: M9-T4
issue: 99
status: planned
depends_on: [96, 72]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M9-T4 — Resumable World Change Feed

## Goal
Expose a read-only stream of committed Timeline changes with cursor-based reconnect and bounded backpressure.

## Required implementation
- Implement Subscription over committed History/ancestry visibility.
- Resume from committed cursor without semantic gap/duplicate according to #96.
- Bound buffering and define slow-subscriber disconnect/backpressure.
- PostgreSQL polling/tailing/notification may wake readers, but correctness always derives from committed history.
- InMemory deterministic feed contract tests.

## Forbidden shortcuts
No subscriber callback in commit, Redis/Kafka requirement, uncommitted feed data or unbounded channel.

## Acceptance checklist
- [ ] committed changes emit in stable order;
- [ ] reconnect/resume passes;
- [ ] subscriber failure cannot affect World;
- [ ] server restart preserves cursor resume;
- [ ] child feed obeys ancestry visibility;
- [ ] adapter parity/architecture gates pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned; parallel-safe after #96.
