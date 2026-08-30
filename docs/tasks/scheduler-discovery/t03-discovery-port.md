---
task: SCHD-T03
issue: 405
status: planned
depends_on: [404]
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T03 — Define bounded Scheduler discovery persistence port

## Goal

Define the smallest Runtime-owned persistence contract for enumerating Timeline
targets that have Pending Scheduler obligations.

## Scope

- Add a narrow storage-neutral discovery port in `loom-runtime`.
- Require a positive bounded page size and deterministic cursor/continuation.
- Return only `WorldId`/`TimelineId` target identity and continuation data.
- Include Pending Work even when its due World Time is in the future or it is
  temporarily unclaimable.
- Use typed invalid-bound and storage errors following existing conventions.

## Boundaries and acceptance

- [ ] The contract is executor- and SQL/storage-type-neutral.
- [ ] Discovery does not decide due-ness, claimability or logical head.
- [ ] No Work IDs, claim tokens, Runtime orchestration or public API are
      exposed.
- [ ] Cursor/bound behavior is precise enough for non-starving scans.
- [ ] Constructor/value tests and affected fmt/check/clippy/tests pass.
