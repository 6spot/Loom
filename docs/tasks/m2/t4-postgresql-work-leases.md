---
task: M2-T4
issue: 29
status: planned
depends_on: [26]
created_at: 2026-08-21
started_at:
completed_at:
completion_pr:
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

- [ ] concurrent claims choose one winner;
- [ ] expired Work can be reclaimed with a new fence;
- [ ] stale fence cannot complete/retry after re-claim;
- [ ] retry preserves Work identity and World Truth;
- [ ] future/unavailable Work cannot be claimed early;
- [ ] cancellation/completion races are atomic and typed;
- [ ] zero-Event successful Work completion persists correctly;
- [ ] architecture, fmt, check, clippy, tests and rustdoc pass.

## Completion evidence

- PR:
- merge SHA:
- concurrency verification:
- CI / verification:
- notes:

## Progress log

- 2026-08-21 — Task record created from issue #29; status `planned`.
