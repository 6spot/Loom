---
task: M2-T5
issue: 30
status: in_progress
depends_on: [26]
created_at: 2026-08-21
started_at: 2026-08-21
completed_at:
completion_pr:
merge_sha:
---

# M2-T5 — PostgreSQL Integration-Test and CI Infrastructure

## Goal

Make PostgreSQL 18 persistence behavior reproducibly testable in local and CI workflows so migration and semantic regressions are continuously enforced.

## Scope

- Repeatable PostgreSQL 18 integration-test environment.
- SQLx migrations applied as database test setup.
- Test credentials/configuration stay in test/application infrastructure.
- PostgreSQL-backed integration/parity tests coexist with fast InMemoryStore tests.
- Test database/schema state is isolated sufficiently for repeated/parallel execution.
- Existing Ubuntu/macOS Rust gates stay intact; a required PostgreSQL persistence gate is added where service support is reliable.

## Acceptance checklist

- [ ] clean CI can start/connect to PostgreSQL 18;
- [ ] migrations run from scratch in CI;
- [ ] PostgreSQL integration tests detect migration/schema/contract regressions;
- [ ] local PostgreSQL test instructions are documented;
- [ ] no credentials/secrets are committed;
- [ ] architecture, fmt, check, clippy, unit tests and rustdoc remain green;
- [ ] PostgreSQL integration suite is green on the completion PR.

## Completion evidence

- PR:
- merge SHA:
- CI runs:
- local verification:
- notes:

## Progress log

- 2026-08-21 — Task record created from issue #30; status `planned`.
- 2026-08-21 — Implementation started on `feat/m2-t5-postgresql-test-infra`; replacing the shared PostgreSQL integration database with isolated temporary databases created from the explicit `LOOM_TEST_POSTGRES_URL` control connection, with migrations applied from scratch and explicit cleanup.
