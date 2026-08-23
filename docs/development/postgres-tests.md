# Local PostgreSQL integration tests

Loom PostgreSQL integration tests use one long-lived local PostgreSQL 18 + pgvector service as a **control database**. Individual test fixtures create a unique child database, apply Loom migrations, run the test, and drop the child database afterwards.

The local service is intentionally bound only to `127.0.0.1` and is not exposed on the machine's public interfaces.

## Run tests

Normal Cargo commands are valid:

```bash
cargo test --workspace --all-features
```

PostgreSQL integration tests do **not** self-skip. When `LOOM_TEST_POSTGRES_URL` is unset or empty, the fixture uses the repository-local default:

```text
postgresql://loom:loom@127.0.0.1:15432/loom_control
```

If that default service is not reachable, the fixture invokes `tools/postgres-test.sh up`, waits for the repository-managed PostgreSQL service, and retries the connection. This keeps a direct `cargo test` from producing a false pass or requiring the caller to remember a special pre-test command.

The repository wrapper remains available when explicitly managing the local service before Cargo is useful:

```bash
bash tools/test.sh --workspace --all-features
```

For one PostgreSQL integration test:

```bash
bash tools/test.sh -p loom-storage --test postgres_schema -- --nocapture
```

When `LOOM_TEST_POSTGRES_URL` is not already set, `tools/test.sh` starts/reuses the repository-managed service, exports the local control-database URL, and delegates to `cargo test`. When an explicit `LOOM_TEST_POSTGRES_URL` is already set, the wrapper uses it as-is and does not start the local Compose service.

`LOOM_TEST_POSTGRES_URL` is the only connection override. Use it for CI or a development topology where the tests cannot reach the repository-managed localhost service. An explicit unreachable URL fails directly; it never falls back to or starts a different database. There is no separate environment switch that enables or disables PostgreSQL test execution.

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

These commands are available when the service needs to be inspected or managed explicitly:

```bash
bash tools/postgres-test.sh up
bash tools/postgres-test.sh status
bash tools/postgres-test.sh logs
bash tools/postgres-test.sh down
```

`down` removes the container/network but preserves the named test volume.

## Development environment

The repository-owned local test environment is defined by `compose.test-db.yaml`, `tools/postgres-test.sh`, `tools/test.sh`, the PostgreSQL test fixture under `crates/loom-storage/tests/support`, and this document. Keep these definitions aligned when the test database configuration changes instead of creating a second operational guide for the same workflow.

If development commands run inside a separate container/network namespace, `127.0.0.1` refers to that container rather than the host. In that deployment model, set `LOOM_TEST_POSTGRES_URL` explicitly to the reachable control database address; the fixture will not try to start the host-local service when an explicit URL is present.

## CI

GitHub Actions uses the same pinned database family, `pgvector/pgvector:0.8.6-pg18`. The general Rust test job uses `tools/test.sh` so its service lifecycle is explicit in CI. The dedicated PostgreSQL contract job uses an ephemeral service and an explicit `LOOM_TEST_POSTGRES_URL` on port 5432.
