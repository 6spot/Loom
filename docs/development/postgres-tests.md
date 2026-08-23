# Local PostgreSQL integration tests

Loom PostgreSQL integration tests use a long-lived local PostgreSQL 18 + pgvector service as a **control database**. Individual test fixtures create a unique child database, apply Loom migrations, run the test, and drop the child database afterwards.

The local service is intentionally bound only to `127.0.0.1` and is not exposed on the machine's public interfaces.

The database family is a test contract, not a convenience recommendation. Every PostgreSQL integration fixture validates the control server before creating its child database: the server must be PostgreSQL 18 and must expose pgvector `0.8.6` through `pg_available_extensions`. Plain `postgres:18`, a different pgvector version, or an ad-hoc PostgreSQL container is therefore an invalid Loom test environment.

## Start the local test database

From the repository root:

```bash
bash tools/postgres-test.sh up
```

On first use this creates `.env.test.local` with a generated local-only password, starts `pgvector/pgvector:0.8.6-pg18`, and publishes PostgreSQL at `127.0.0.1:15432` by default.

The generated `.env.test.local` is ignored by Git. `.env.test.example` documents the variables without containing a real credential.

Useful service commands:

```bash
bash tools/postgres-test.sh status
bash tools/postgres-test.sh logs
bash tools/postgres-test.sh down
```

`down` removes the container/network but preserves the named test volume, so the control database survives normal restarts.

## Run tests

Use the repository test wrapper instead of manually exporting PostgreSQL variables:

```bash
bash tools/test.sh --workspace --all-features
```

For one PostgreSQL integration test:

```bash
bash tools/test.sh -p loom-storage --test postgres_schema -- --nocapture
```

`tools/test.sh` loads `.env.test.local`, requires `LOOM_TEST_POSTGRES_URL`, sets `LOOM_REQUIRE_POSTGRES_TESTS=1`, and then delegates to `cargo test`.

The control connection defaults to:

```text
postgresql://loom:<generated-password>@127.0.0.1:15432/loom_control
```

The `loom` role created by the PostgreSQL image is the initialization superuser and therefore can create/drop the isolated databases required by `crates/loom-storage/tests/support`.

## Agent/Codex usage

Agents running commands directly on this development machine must reuse the repository-managed database and invoke PostgreSQL-dependent tests through `bash tools/test.sh ...`.

Do **not** use `docker pull postgres:18`, `docker run ... postgres:18`, or create a second PostgreSQL container to satisfy Loom tests. Do **not** replace `pgvector/pgvector:0.8.6-pg18` with the plain PostgreSQL image. The test harness enforces the pgvector image contract and will reject such an environment.

If an agent is ever moved into a separate container/network namespace, `127.0.0.1` will refer to that container rather than the host. In that deployment model the host connection must be configured explicitly instead of exposing PostgreSQL on all interfaces.

## CI

GitHub Actions uses the same pinned database family, `pgvector/pgvector:0.8.6-pg18`, but its service is ephemeral and CI-owned. Local development and CI therefore exercise PostgreSQL 18 with the same pgvector image while retaining independent lifecycle management.
