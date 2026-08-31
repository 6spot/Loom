# Agent verification guide

Verification must match the changed contract. Do not blindly run every repository check for every edit, and do not skip the owning-layer checks that matter.

## 1. Start narrow, expand by impact

Use this sequence:

```text
changed file/contract
→ owning-layer check
→ architecture/dependency check if crossed
→ PostgreSQL check if persistence is touched
→ deployment check if container/config is touched
→ broader workspace check only when justified
```

The goal is useful evidence, not maximum command count.

## 2. Common checks

Formatting:

```bash
cargo fmt --all -- --check
```

Workspace compile:

```bash
cargo check --workspace --all-targets --all-features
```

Lint:

```bash
cargo clippy --workspace --all-targets --all-features -- -D warnings
```

Architecture/dependency rules:

```bash
python3 tools/check_architecture.py
python3 tools/check_storage_sql_ownership.py
cargo deny check advisories bans licenses sources
```

Run these when the changed surface makes them relevant. A documentation-only edit normally does not justify compiling the whole workspace.

## 3. PostgreSQL-backed work

For Storage, migrations, PostgreSQL-backed Runtime behavior or integration tests, read and follow:

- `docs/development/postgres-tests.md`;
- `tools/postgres-test.sh`;
- `compose.test-db.yaml`.

Do not assume a plain `cargo test` invocation reproduces the repository's PostgreSQL integration-test environment.

Do not restore old test environment variables from memory. Use the current documented procedure.

## 4. Deployment work

For `compose.yaml`, `.env.example`, `Dockerfile`, `docker/` or deployment-guide changes, inspect the rendered configuration:

```bash
docker compose -f compose.yaml config --quiet
docker compose -f compose.yaml config
```

When changing environment-variable wiring, verify that the expected variables actually appear under the rendered `loom-server` environment.

## 5. CI routing is change-aware

Before predicting CI requirements, inspect current workflows under `.github/workflows/`.

The core CI currently classifies changes into focused lanes such as Rust, dependency, Task Ledger, PostgreSQL, deployment and documentation. Treat the workflow itself as current operational truth.

Examples:

- prose documentation should not automatically force full Rust/PostgreSQL validation;
- a Storage/SQL change requires PostgreSQL-aware verification;
- a Cargo dependency change requires dependency/architecture checks;
- Compose/Docker changes require deployment validation.

Do not maintain a static duplicated CI matrix in this guide.

## 6. Evidence rules

Only report a check as passed if it actually ran and succeeded.

Use explicit states in completion notes when helpful:

- `PASS` — command ran successfully;
- `FAIL` — command ran and failed;
- `NOT RUN` — intentionally not run, with reason;
- `BLOCKED` — environment/tooling prevented verification, with reason.

Do not infer current success from an older commit, another branch, an unrelated CI lane or another Agent's report.

## 7. Final verification review

Before finishing, ask:

- Did I test the layer that owns the changed contract?
- Did the change cross a dependency/authority boundary?
- Did it touch durable PostgreSQL behavior?
- Did it change deployment or environment wiring?
- Did I run expensive checks that add no evidence?
- Did I omit a focused check that would catch the likely failure mode?

Prefer a small, defensible verification set over both extremes: "run nothing" and "run everything."