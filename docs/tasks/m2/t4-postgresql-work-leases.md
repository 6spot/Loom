---
task: M2-T4
issue: 29
status: in_progress
depends_on: [26]
created_at: 2026-08-21
started_at: 2026-08-21
completed_at:
completion_pr: 40
merge_sha:
---

# M2-T4 — PostgreSQL Durable Work Lease, Claim and Retry Fencing

## Goal

Implement PostgreSQL-backed Durable Work lifecycle operations while preserving Runtime-owned lease/fence and Platform Time semantics.

## Scope

- Implement PostgreSQL `WorkStore` operations.
- Use explicit concurrent claim SQL, including `FOR UPDATE SKIP LOCKED` where appropriate.
- Claims remain leases/fences rather than durable World `Running` state.
- Fence generations reject stale completion/retry attempts.
- Lease expiry and retry availability use Platform Time only.
- Technical retry changes Work operational metadata but not World Truth.
- Successful Work completion remains atomic with resulting CommitStore changes.

## Acceptance checklist

- [x] concurrent claims choose one winner;
- [x] expired Work can be reclaimed with a new fence;
- [x] stale fence cannot complete/retry after re-claim;
- [x] retry preserves Work identity and World Truth;
- [x] future/unavailable Work cannot be claimed early;
- [x] cancellation/completion races are atomic and typed;
- [x] zero-Event successful Work completion persists correctly;
- [x] architecture, fmt, check, clippy, tests and rustdoc pass.

## Completion evidence

- PR: #40
- merge SHA: pending implementation merge; recorded only by the immediate post-merge audit.
- concurrency verification: PostgreSQL 18 tests cover one-winner concurrent claim, expired-lease reclaim with increasing fence generation, stale retry rejection, stale completion rejection after reclaim, and typed completion/cancellation race.
- CI / verification: clean implementation CI run `32460351746` passed Ubuntu and macOS Architecture, Format, Check, Clippy, Test and Rustdoc plus the PostgreSQL 18 persistence contract.
- notes: `WorkStore` persistence I/O is executor-neutral Future-returning; SQLx and `PgPool` remain confined to `loom-storage`. Claims/retries mutate only platform/lease metadata; successful Work completion remains part of the Runtime-authorized atomic commit.

## Progress log

- 2026-08-21 — Task record created from issue #29; status `planned`.
- 2026-08-21 — Implementation started on `feat/m2-t4-postgresql-work-leases`; `WorkStore` I/O will become executor-neutral Future-returning so SQLx remains confined to `loom-storage` without Runtime-side blocking.
- 2026-08-21 — PostgreSQL Work claim/retry/read adapter, lease fencing, expiry reclaim, Runtime async forwarding and concurrency/race tests implemented; temporary branch-local source-application tooling removed before final review.
- 2026-08-21 — Clean implementation head passed CI run `32460351746`; acceptance checklist verified. Task remains `in_progress` until PR #40 is merged and the real merge SHA is recorded by the immediate audit PR.
