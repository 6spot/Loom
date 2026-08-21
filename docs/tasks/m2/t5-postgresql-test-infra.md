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
- 2026-08-21 — Added the shared `tests/support` harness: each PostgreSQL fixture creates a unique child database, applies embedded SQLx migrations from scratch, and drops the database with forced connection cleanup. Dynamic database DDL is restricted to harness-generated identifiers and explicitly audited with SQLx `AssertSqlSafe`.
- 2026-08-21 — Migrated read, commit/CAS, Durable Work, and stale-completion integration suites to the isolated harness and added a dedicated PostgreSQL 18 schema/migration contract. Branch-local verifier run `32462337002` passed workspace check/clippy and all five PostgreSQL suites before the temporary write-enabled verifier workflow and transformation helpers were removed.
- 2026-08-21 — Standard read-only CI now runs schema/migration, read parity, commit/CAS, Durable Work, and stale Work-fence suites as explicit required PostgreSQL 18 steps. Local Docker/test instructions are documented in `docs/testing-postgresql.md`; clean-head CI evidence is pending before acceptance is marked complete.
