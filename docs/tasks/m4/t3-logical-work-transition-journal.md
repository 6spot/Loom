---
task: M4-T3
issue: 63
status: planned
depends_on: [61, 62]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M4-T3 — Logical Work Transition Journal

## Goal

Represent reconstructable Durable Work logical evolution without contaminating World history with platform retry bookkeeping.

## Required implementation

- Add Runtime-owned logical transitions for at least Work Scheduled, Cancelled and Completed.
- Record Timeline/version before/after, Work identity, semantic mutation and causal Event/Work origin required to reconstruct unresolved obligations.
- Keep lease, fence, attempt count, `last_error` and retry/backoff bookkeeping outside logical history unless M4-T1 explicitly classifies a field otherwise.
- Represent Work-only logical commits and atomic current-Work completion plus resulting World commit.
- Add deterministic reconstruction helpers/tests over transition streams.

## Forbidden shortcuts

- No fake World Events for Work lifecycle.
- No lease/retry history copied into the logical journal.
- No second commit authority and no historical fork implementation here.

## Acceptance checklist

- [ ] schedule/cancel/complete transitions are typed/documented;
- [ ] Work-only commit behavior matches #61;
- [ ] unresolved obligations reconstruct from transition history;
- [ ] technical retry/claim noise cannot change logical reconstruction;
- [ ] InMemory tests cover Event+Work, Work-only and completion paths;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence

- PR:
- merge SHA:
- verification:

## Progress log

- 2026-08-22 — Planned after replay contract/engine foundations.
