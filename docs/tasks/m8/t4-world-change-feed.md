---
task: M8-T4
issue: 177
status: planned
depends_on: [166, 174]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M8-T4 — Resumable committed World Change Feed

- Subscription reads committed ancestry-aware Event history only.
- Stable cursor/reconnect semantics; explicit duplicate-delivery behavior if needed, no semantic gaps.
- Bounded buffering/backpressure and slow-subscriber policy.
- Subscriber presence/health never participates in authority transaction.
- PostgreSQL notification may wake readers, but history remains correctness source after lost notification/restart.

## Acceptance
- [ ] Order/cursor exact across branches.
- [ ] Restart/resume loses no committed change.
- [ ] Slow/broken subscriber cannot block commit.
- [ ] Bounded memory + InMemory/PostgreSQL parity + standard gates pass.

## Verification evidence
Pending.