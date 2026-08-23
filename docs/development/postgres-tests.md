# Local PostgreSQL integration tests

Loom PostgreSQL integration tests use a long-lived local PostgreSQL 18 + pgvector service as a **control database**. Individual test fixtures create a unique child database, apply Loom migrations, run the test, and drop the child database afterwards.

The local service is intentionally bound only to `127.0.0.1` and is not exposed on the machine's public interfaces.

## Run tests

Use the repository test wrapper:

```bash
bash tools/test.sh --workspace --all-features
```

For one PostgreSQL integration test:

```bash
bash tools/test.sh -p loom-storage --test postgres_schema -- --nocapture
```

No separate PostgreSQL setup step is required. On first use, `tools/test.sh` calls `tools/postgres-test.sh up`, which creates the ignored `.env.test.local` with a generated local-only password, starts `pgvector/pgvector:0.8.6-pg18`, waits for its health check, and publishes PostgreSQL at `127.0.0.1:15432` by default. It then loads the generated environment, requires PostgreSQL integration tests, and delegates to `cargo test`.

The generated `.env.test.local` is ignored by Git. `.env.test.example` documents the variables without containing a real credential.

The control connection defaults to:

```text
postgresql://loom:<generated-password>@127.0.0.1:15432/loom_control
```

The `loom` role created by the PostgreSQL image is the initialization superuser and therefore can create/drop the isolated databases required by `crates/loom-storage/tests/support`.

## Manage the local service

The test wrapper normally manages startup automatically. These commands are available when the service needs to be inspected or managed explicitly:

```bash
bash tools/postgres-test.sh up
bash tools/postgres-test.sh status
bash tools/postgres-test.sh logs
bash tools/postgres-test.sh down
```

`down` removes the container/network but preserves the named test volume, so the control database survives normal restarts.

## Development environment

The repository-owned local test environment is defined by `compose.test-db.yaml`, `.env.test.example`, `tools/postgres-test.sh`, and this document. Keep these definitions aligned when the test database configuration changes instead of creating a second operational guide for the same workflow.

If development commands run inside a separate container/network namespace, `127.0.0.1` refers to that container rather than the host. In that deployment model the host connection must be configured explicitly instead of exposing PostgreSQL on all interfaces.

## CI

GitHub Actions uses the same pinned database family, `pgvector/pgvector:0.8.6-pg18`, but its service is ephemeral and CI-owned. Local development and CI therefore exercise PostgreSQL 18 with the same pgvector image while retaining independent lifecycle management.
