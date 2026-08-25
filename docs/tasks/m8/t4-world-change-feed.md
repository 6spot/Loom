---
task: M8-T4
issue: 177
status: completed
depends_on: [166, 174]
created_at: 2026-08-22
started_at: 2026-08-24
completed_at: 2026-08-24
completion_pr: 233
merge_sha: 983b668407fb1aaffdfdfb29c5b3dc4a3a95ffc9
---
# M8-T4 — Resumable committed World Change Feed

- Subscription reads committed ancestry-aware Event history only.
- Stable cursor/reconnect semantics; explicit duplicate-delivery behavior if needed, no semantic gaps.
- Bounded buffering/backpressure and slow-subscriber policy.
- Subscriber presence/health never participates in authority transaction.
- PostgreSQL notification may wake readers, but history remains correctness source after lost notification/restart.

## Acceptance
- [x] Order/cursor exact across branches.
- [x] Restart/resume loses no committed change.
- [x] Slow/broken subscriber cannot block commit.
- [x] Bounded memory + InMemory/PostgreSQL parity + standard gates pass.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.