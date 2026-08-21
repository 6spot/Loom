---
task: M2-T5
issue: 30
status: completed
depends_on: [26]
created_at: 2026-08-21
started_at: 2026-08-21
completed_at: 2026-08-21
completion_pr: 42
merge_sha: 9f2051d3098b1b321508bff115390541646f1a41
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

- [x] clean CI can start/connect to PostgreSQL 18;
- [x] migrations run from scratch in CI;
- [x] PostgreSQL integration tests detect migration/schema/contract regressions;
- [x] local PostgreSQL test instructions are documented;
- [x] no credentials/secrets are committed;
- [x] architecture, fmt, check, clippy, unit tests and rustdoc remain green;
- [x] PostgreSQL integration suite is green on the completion PR.

## Completion evidence

- PR: #42
- merge SHA: `9f2051d3098b1b321508bff115390541646f1a41`
- CI runs: branch-local migration verifier `32462337002`; clean implementation CI `32463175121`; final task-record CI `32463486023`
- local verification: `docs/testing-postgresql.md` documents the PostgreSQL 18 Docker control database plus the exact five `cargo test -p loom-storage --test ...` commands used by CI.
- notes: each PostgreSQL integration fixture provisions a unique child database, runs embedded SQLx migrations from scratch, and drops it after the test. The committed workflow retains `contents: read`; the temporary write-enabled migration verifier and helper scripts were removed before final acceptance. Repository credentials are only disposable local/CI test values, not production secrets.

## Progress log

- 2026-08-21 — Task record created from issue #30; status `planned`.
- 2026-08-21 — Implementation started on `feat/m2-t5-postgresql-test-infra`; replacing the shared PostgreSQL integration database with isolated temporary databases created from the explicit `LOOM_TEST_POSTGRES_URL` control connection, with migrations applied from scratch and explicit cleanup.
- 2026-08-21 — Added the shared `tests/support` harness: each PostgreSQL fixture creates a unique child database, applies embedded SQLx migrations from scratch, and drops the database with forced connection cleanup. Dynamic database DDL is restricted to harness-generated identifiers and explicitly audited with SQLx `AssertSqlSafe`.
- 2026-08-21 — Migrated read, commit/CAS, Durable Work, and stale-completion integration suites to the isolated harness and added a dedicated PostgreSQL 18 schema/migration contract. Branch-local verifier run `32462337002` passed workspace check/clippy and all five PostgreSQL suites before the temporary write-enabled verifier workflow and transformation helpers were removed.
- 2026-08-21 — Standard read-only CI now runs schema/migration, read parity, commit/CAS, Durable Work, and stale Work-fence suites as explicit required PostgreSQL 18 steps. Local Docker/test instructions are documented in `docs/testing-postgresql.md`.
- 2026-08-21 — Clean standard CI run `32463175121` passed PostgreSQL 18 schema/migration, read, commit/CAS, Durable Work and stale-fence suites plus Ubuntu/macOS Architecture, Format, Check, Clippy, Test and Rustdoc.
- 2026-08-21 — Final task-record CI run `32463486023` passed the same standard read-only gates; PR #42 merged as `9f2051d3098b1b321508bff115390541646f1a41`, and this post-merge audit records the real implementation merge SHA.
