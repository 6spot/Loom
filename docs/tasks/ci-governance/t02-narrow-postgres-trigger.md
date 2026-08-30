---
task: CI-GOV-T02
issue: 431
status: completed
depends_on: [CI-GOV-T01]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at: 2026-08-30
completion_pr: 434
merge_sha: 66de022bc78c2988af19fe045a66c11152d9909a
---

# CI-GOV-T02 — Narrow PostgreSQL CI triggering

## Scope

Keep the PostgreSQL 18 persistence-contract lane scoped to changes that can actually affect PostgreSQL persistence behavior.

This task changes only CI governance:

- `Cargo.lock` continues to trigger dependency-policy and ordinary Rust validation;
- existing Validator routing for `Cargo.lock` remains unchanged;
- `Cargo.lock` no longer sets `postgres=true` by itself;
- Storage, SQL, PostgreSQL test infrastructure, and CI-authority changes keep their existing PostgreSQL routing.

No Runtime, Storage, Scheduler, API, Validator, schema, SQL, dependency-version, or architecture semantics are in scope.

## Acceptance

- [x] `Cargo.lock` classifier branch does not set `postgres=true`.
- [x] `Cargo.lock` still sets `dependency=true`, `rust=true`, and the pre-existing `validator=true`.
- [x] `crates/loom-storage/**` still triggers the PostgreSQL lane.
- [x] SQL files still trigger the PostgreSQL lane.
- [x] `compose.test-db.yaml` and `tools/postgres-test.sh` still trigger the PostgreSQL lane.
- [x] CI-authority changes still validate every route once.
- [x] No production or architecture semantics change.

## Progress Log

- 2026-08-30 — Started as dedicated CI governance issue #431 after reviewing the split classifier on current `main`. The intended change is one routing deletion: remove the generic PostgreSQL side effect from the `Cargo.lock` branch while preserving every persistence-specific trigger.
- 2026-08-30 — Delivery PR #434 opened. Its workflow diff is exactly one deleted line; the remaining changes are this task record and the CI governance index.
- 2026-08-30 — PR #434 passed every CI route and merged as `66de022bc78c2988af19fe045a66c11152d9909a`.

## Verification Evidence

PR #434 CI run `33309170240` passed all routed jobs:

- change classification;
- dependency and security policy;
- Rust architecture/fmt/check/clippy/unit/Rustdoc lane;
- PostgreSQL 18 persistence contract lane;
- Loom server Compose config lane;
- task-ledger governance;
- current Validator regression lane.

The delivery workflow diff was exactly one deletion: the `postgres=true` assignment from the `Cargo.lock` classifier branch. Persistence-specific PostgreSQL triggers remained unchanged.
