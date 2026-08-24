---
task: VAL-T1
issue: 253
status: in_progress
depends_on: []
created_at: 2026-08-24
started_at: 2026-08-25
completed_at:
completion_pr:
merge_sha:
---
# VAL-T1 — Validator skeleton and public-consumer dependency fence

Create the first-party `apps/loom-validator` consumer without introducing a
shadow Loom API or accessing implementation-only Runtime/Storage authority.

## Acceptance

- [ ] Workspace builds with `apps/loom-validator`.
- [ ] The dependency/import fence rejects forbidden validator dependencies and
  imports.
- [ ] The validator starts and enumerates an empty/bootstrap scenario registry.
- [ ] The validator initiative index and this Task Ledger record follow the
  repository audit conventions.
- [ ] Relevant format, check, clippy, and test gates pass.

## Scope

- Public consumer surface: `loom-client`.
- Validator modules: scenario registry, runner, backend context, reports, and
  Task Ledger feedback.
- Mechanical enforcement: extend
  `tools/check_storage_sql_ownership.py` with validator-specific checks.

No direct SQL/PgStorage access, test-only Runtime handles, or future scenario
semantics are part of this skeleton.

## Progress Log

- 2026-08-25 — Started the public-consumer skeleton and validator fence under
  the acceptance scope of GitHub issue #253.

## Verification Evidence

- `python3 tools/check_storage_sql_ownership.py` → passed for the clean
  validator tree.
- Temporary `loom_storage::PgStorage` import → the validator fence failed with
  both the forbidden import and authority diagnostics; the temporary fixture
  was removed.
- Temporary `loom-storage` validator dependency → the validator fence failed
  with the implementation workspace dependency diagnostic; the temporary
  fixture was removed.
- `python3 tools/check_architecture.py` → storage SQL ownership and workspace
  dependency policy passed.
- `cargo fmt --all -- --check` → passed.
- `cargo check -p loom-validator` → passed.
- `cargo check --workspace --all-targets --all-features` → passed.
- `cargo clippy -p loom-validator --all-targets --all-features -- -D warnings`
  → passed.
- `cargo test -p loom-validator` → 2 unit tests passed.
- `cargo run -q -p loom-validator` → `loom-validator: enumerated 0 scenario(s)`.

Acceptance remains pending reviewer confirmation.
