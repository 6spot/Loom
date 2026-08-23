# Local PostgreSQL integration tests

Loom PostgreSQL integration tests use one long-lived local PostgreSQL 18 + pgvector service as a **control database**. Individual test fixtures create a unique child database, apply Loom migrations, run the test, and drop the child database afterwards.

The local service is intentionally bound only to `127.0.0.1` and is not exposed on the machine's public interfaces.

## Run tests

The recommended entry point is the repository test wrapper:

```bash
bash tools/test.sh --workspace --all-features
```

For one PostgreSQL integration test:

```bash
bash tools/test.sh -p loom-storage --test postgres_schema -- --nocapture
```

No separate PostgreSQL setup step is required when using the wrapper. `tools/test.sh` ensures the repository-managed service is running, waits for its health check, exports the effective control-database URL, and then delegates to `cargo test`.

PostgreSQL integration tests do **not** self-skip. When `LOOM_TEST_POSTGRES_URL` is unset or empty, the test fixture uses the repository-local default:

```text
postgresql://loom:loom@127.0.0.1:15432/loom_control
```

This means a direct `cargo test` also runs PostgreSQL integration bodies when the local service is already available. If the control database cannot be reached, the PostgreSQL test fails with an instruction to start the repository-managed service instead of reporting a false pass.

`LOOM_TEST_POSTGRES_URL` is the only connection override. Use it for CI or a development topology where the tests cannot reach the repository-managed localhost service. There is no separate environment switch that enables or disables PostgreSQL test execution.

## Local service contract

The repository-managed service is deliberately fixed:

```text
image: pgvector/pgvector:0.8.6-pg18
user: loom
password: loom
database: loom_control
address: 127.0.0.1:15432
compose project: loom
```

These are local-test-only values, not deployment credentials. The fixed Compose project name makes every checkout and Multica worktree on the same host address the same container and named volume instead of creating per-worktree PostgreSQL services.

Docker Compose reuses the existing image, container and named volume when their configuration already matches. It pulls the image or creates service state only when missing. The named volume preserves the control database across normal container restarts.

Older test volumes may have been initialized with a generated password. `tools/postgres-test.sh up` reconciles the local `loom` role to the current fixed test password after PostgreSQL becomes healthy, so an old volume does not require a manual reset.

The configured role can create/drop databases because `crates/loom-storage/tests/support` provisions an isolated database per fixture.

## Manage the local service

The test wrapper normally manages startup automatically. These commands are available when the service needs to be inspected or managed explicitly:

```bash
bash tools/postgres-test.sh up
bash tools/postgres-test.sh status
bash tools/postgres-test.sh logs
bash tools/postgres-test.sh down
```

`down` removes the container/network but preserves the named test volume.

## Development environment

The repository-owned local test environment is defined by `compose.test-db.yaml`, `tools/postgres-test.sh`, `tools/test.sh`, the PostgreSQL test fixture under `crates/loom-storage/tests/support`, and this document. Keep these definitions aligned when the test database configuration changes instead of creating a second operational guide for the same workflow.

If development commands run inside a separate container/network namespace, `127.0.0.1` refers to that container rather than the host. In that deployment model, set `LOOM_TEST_POSTGRES_URL` explicitly to the reachable control database address.

## CI

GitHub Actions uses the same pinned database family, `pgvector/pgvector:0.8.6-pg18`. The general Rust test job uses `tools/test.sh` so workspace tests cannot silently omit PostgreSQL integration bodies. The dedicated PostgreSQL contract job uses an ephemeral service and an explicit `LOOM_TEST_POSTGRES_URL` on port 5432.
