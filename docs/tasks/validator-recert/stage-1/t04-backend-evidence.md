---
task: VALR-T04
issue: 307
status: completed
depends_on: []
created_at: 2026-08-26
started_at: 2026-08-26
completed_at: 2026-08-26
completion_pr: 331
merge_sha: 9617979e02bb095484182c0c57e3c3b8e8d6b7a2
---
# VALR-T04 — Trusted backend evidence identities

## Acceptance

- [x] backend identity is derived from explicit controlled construction, not
      ambient `LOOM_TEST_POSTGRES_URL` presence;
- [x] generic/external, controlled InMemory, and controlled PostgreSQL
      evidence classes are visible in reports;
- [x] required-live policy accepts only trusted PostgreSQL evidence;
- [x] production Validator code remains on `loom-api`/`loom-client` public
      surfaces;
- [x] focused regression tests cover valid and malformed ambient PG data;
- [x] review and required CI gates complete.

## Progress Log

- 2026-08-26 — Added the explicit `BackendEvidence` model, context/harness
  accessors and construction seam, report metadata/trust fields, and required
  live evidence gating. Removed CLI inference from `LOOM_TEST_POSTGRES_URL`.
- 2026-08-26 — Added subprocess regression coverage for generic HTTP endpoints
  with valid and malformed PG configuration, plus controlled InMemory and
  PostgreSQL evidence tests.
- 2026-08-26 — PR #331 was independently reviewed, all required CI checks
  passed, and the change merged at `9617979e02bb095484182c0c57e3c3b8e8d6b7a2`.

## Verification Evidence

- `cargo fmt --all` → passed.
- `cargo fmt --all -- --check` → passed.
- `cargo check -p loom-validator --all-targets --all-features` → passed.
- `cargo check --workspace --all-targets --all-features` → passed.
- `cargo test -p loom-validator --test backend_evidence --all-features` →
  passed (1 test; valid and malformed ambient PG cases).
- `cargo clippy -p loom-validator --all-targets --all-features -- -D warnings`
  → passed.
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` →
  passed.
- `bash tools/test.sh -p loom-validator --all-features` → passed (101 unit
  tests, backend-evidence regression, 3 lifecycle tests, 4 replay/fork tests,
  and 2 runtime-authority tests with the managed PostgreSQL 18 service).
- `python3 tools/check_storage_sql_ownership.py` → passed.
- `python3 tools/check_architecture.py` → passed.
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert/stage-1
  --check --format json` → valid; VALR-T04 is the sole open leaf.

Acceptance complete: Reviewer approved PR #331, both required CI checks passed,
and the merged delivery is recorded above.
