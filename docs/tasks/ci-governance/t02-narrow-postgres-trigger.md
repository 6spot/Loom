---
task: CI-GOV-T02
issue: 431
status: in_progress
depends_on: [CI-GOV-T01]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at:
completion_pr:
merge_sha:
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

- [ ] `Cargo.lock` classifier branch does not set `postgres=true`.
- [ ] `Cargo.lock` still sets `dependency=true`, `rust=true`, and the pre-existing `validator=true`.
- [ ] `crates/loom-storage/**` still triggers the PostgreSQL lane.
- [ ] SQL files still trigger the PostgreSQL lane.
- [ ] `compose.test-db.yaml` and `tools/postgres-test.sh` still trigger the PostgreSQL lane.
- [ ] CI-authority changes still validate every route once.
- [ ] No production or architecture semantics change.

## Progress Log

- 2026-08-30 — Started as dedicated CI governance issue #431 after reviewing the split classifier on current `main`. The intended change is one routing deletion: remove the generic PostgreSQL side effect from the `Cargo.lock` branch while preserving every persistence-specific trigger.

## Verification Evidence

Pending delivery PR CI and merge evidence.
