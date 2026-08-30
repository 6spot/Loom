---
task: SCHD-T03
issue: 405
status: completed
depends_on: [404]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at: 2026-08-30
completion_pr: 426
merge_sha: 61651b454a29eb7bfadbebddf61b31a88a4eda7b
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

- [x] The contract is executor- and SQL/storage-type-neutral.
- [x] Discovery does not decide due-ness, claimability or logical head.
- [x] No Work IDs, claim tokens, Runtime orchestration or public API are
      exposed.
- [x] Cursor/bound behavior is precise enough for non-starving scans.
- [x] Constructor/value tests and affected fmt/check/clippy/tests pass.

## Completion evidence

- Delivery PR #426 merged on 2026-08-30 as
  `61651b454a29eb7bfadbebddf61b31a88a4eda7b`.
