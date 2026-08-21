# PostgreSQL 18 persistence tests

Loom's PostgreSQL integration tests use a **control database** only to provision isolated test databases. Each test fixture creates a unique empty database, applies the embedded SQLx migrations from scratch, runs its assertions, closes its pools, and drops that database with `DROP DATABASE ... WITH (FORCE)`.

The test harness is intentionally owned by `loom-storage` test infrastructure. Core, Protocol, API, Capability, Agency, and Runtime contracts do not receive database URLs or SQLx types.

## Local PostgreSQL 18 service

A disposable Docker service matching CI can be started with:

```bash
docker run --rm --name loom-postgres-test \
  -e POSTGRES_USER=loom \
  -e POSTGRES_PASSWORD=loom \
  -e POSTGRES_DB=loom_control \
  -p 5432:5432 \
  postgres:18
```

The `loom` credentials above are deliberately local/disposable test credentials, not deployment credentials or repository secrets. The control role must be allowed to create and drop databases because isolation is database-per-fixture.

In another shell:

```bash
export LOOM_TEST_POSTGRES_URL='postgresql://loom:loom@localhost:5432/loom_control'
export LOOM_REQUIRE_POSTGRES_TESTS=1

cargo test -p loom-storage --test postgres_schema -- --nocapture
cargo test -p loom-storage --test postgres_read -- --nocapture
cargo test -p loom-storage --test postgres_commit -- --nocapture
cargo test -p loom-storage --test postgres_work -- --nocapture
cargo test -p loom-storage --test postgres_work_stale_completion -- --nocapture
```

`LOOM_REQUIRE_POSTGRES_TESTS=1` makes a missing `LOOM_TEST_POSTGRES_URL` a hard failure. Without that flag, PostgreSQL-specific integration tests skip when no control URL is configured, so the normal fast workspace unit/contract suite remains usable without a local database.

## CI contract

`.github/workflows/ci.yml` runs the same five suites against the official `postgres:18` service on Ubuntu. The job uses an ephemeral `loom_control` database, and the integration harness creates isolated child databases for the schema/migration, read, commit/CAS, Durable Work, and stale-fence suites.

The schema suite verifies PostgreSQL major version 18, proves migrations apply to a newly created empty database, checks SQLx migration history, re-runs unchanged migrations, and exercises representative database constraints. The other suites then verify authoritative read, commit/CAS/concurrency, Work lease/retry/fencing, and stale-completion semantics without sharing state between test fixtures.
