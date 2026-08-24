---
task: VAL-T4
issue: 256
status: in_progress
depends_on: [254]
created_at: 2026-08-24
started_at: 2026-08-25
completed_at:
completion_pr:
merge_sha:
---
# VAL-T4 — InMemory/PostgreSQL backend harness and prerequisite semantics

Provide repeatable public-consumer contexts so one validator scenario can be
run against deterministic InMemory and repository-composed live PostgreSQL
realizations without hiding missing live prerequisites.

## Acceptance

- [ ] The same synthetic scenario can execute on both backend kinds.
- [ ] An absent `LOOM_TEST_POSTGRES_URL` is visible as an explicit
  prerequisite/unavailable result, never `pass`.
- [ ] Strict/required-live mode fails the runner gate when PostgreSQL evidence
  is required but unavailable.
- [ ] Backend cleanup prevents cross-scenario context/state leakage.
- [ ] Validator scenarios do not import SQLx, `PgStorage`, Runtime, or other
  implementation-only authority.
- [ ] Standard Rust and validator boundary gates pass.

## Scope

- `BackendHarness` owns the public-consumer lifecycle seam: `connect`,
  `start`, and `dispose`.
- `BackendContext` exposes only `LoomClient` plus non-authoritative backend and
  deterministic scenario-scope metadata.
- InMemory starts a fresh public context for each scenario scope.
- PostgreSQL checks `LOOM_TEST_POSTGRES_URL` before endpoint construction and
  observes the repository-supported test/deployment composition path. Database
  process startup and migrations remain owned by the repository composition
  root (`compose.test-db.yaml`/test tooling), not by scenario code.
- `ValidationPolicy` and `ValidationReport` preserve explicit prerequisite and
  unavailable outcomes and enforce strict/required-live gates.

No direct SQL/Storage authority, scenario-specific runner selection, process
exit policy, or remediation policy is part of this task.

## Progress Log

- 2026-08-25 — Added public-consumer backend lifecycle harness, PostgreSQL
  prerequisite classification, deterministic per-scenario contexts, cleanup,
  and strict/required-live report gates under GitHub issue #256.

## Verification Evidence

- `cargo fmt --all -- --check` → passed.
- `cargo check -p loom-validator` → passed.
- `cargo test -p loom-validator` → 25 tests passed.
- `cargo clippy -p loom-validator --all-targets --all-features -- -D warnings`
  → passed.
- `cargo check --workspace --all-targets --all-features` → passed.
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` →
  passed.
- `cargo test --workspace --all-features` → passed, including repository
  InMemory and PostgreSQL composition suites.
- `python3 tools/check_storage_sql_ownership.py` → passed.
- `python3 tools/check_architecture.py` → passed.
- Live validator HTTP execution against a configured PostgreSQL endpoint was
  not run in this implementation turn; the harness reports that prerequisite
  explicitly when `LOOM_TEST_POSTGRES_URL` is absent.

Acceptance remains pending reviewer confirmation.
