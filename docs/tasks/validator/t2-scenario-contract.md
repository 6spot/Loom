---
task: VAL-T2
issue: 254
status: planned
depends_on: ["VAL-T1"]
created_at: 2026-08-24
started_at:
completed_at:
completion_pr:
merge_sha:
---
# VAL-T2 — Stable scenario IDs, registry, and result contract

Define the stable contract used by all current and future validator scenarios on the public-consumer surface.

## Acceptance

- [ ] duplicate scenario IDs are rejected;
- [ ] registry enumeration order is deterministic;
- [ ] missing prerequisites cannot serialize/render as `pass`;
- [ ] finding payload contains no remediation/suggested-fix authority field;
- [ ] contract tests and standard Rust gates pass.

## Scope

- Stable IDs such as `CV-001`, independent of Rust function/file names.
- Scenario metadata: name, capability area, supported backend set, prerequisite description, related task(s), and optional architecture references.
- Result states at minimum `pass`, `fail`, and explicit prerequisite/environment `skipped`/`unavailable`.
- Structured finding payload containing scenario, expected, actual, backend/context, and evidence references.
- Registry supports deterministic enumeration and lookup by ID.
- Contract is extensible without scenario-specific branching in the runner.

No direct Runtime/Storage authority, shadow API, or broad scenario coverage is part of this contract leaf.

## Progress Log

- 2026-08-25 — Started stable scenario contract implementation under GitHub issue #254; implemented `ScenarioId`, `ScenarioDescriptor`, `ScenarioOutcome`, `Finding`, `ScenarioRegistry`, and runner extensibility.

## Verification Evidence

- `cargo fmt --all -- --check` → passed.
- `cargo check -p loom-validator` → passed.
- `cargo check --workspace --all-targets --all-features` → passed.
- `cargo clippy -p loom-validator --all-targets --all-features -- -D warnings` → passed.
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` → passed.
- `cargo test -p loom-validator` → 19 tests passed.
- `python3 tools/check_storage_sql_ownership.py` → passed.
- `python3 tools/check_architecture.py` → passed.
- `cargo run -q -p loom-validator` → `loom-validator: enumerated 0 scenario(s)`.
- Duplicate ID rejection verified via `registry::tests::duplicate_ids_are_rejected`.
- Deterministic enumeration verified via `registry::tests::enumeration_order_is_deterministic`.
- Missing prerequisite non-pass verified via `outcome::tests::skipped_is_not_pass` and `finding::tests::skipped_finding_does_not_render_as_pass`.
- No remediation field verified via `finding::tests::finding_has_no_remediation_field`.

Acceptance remains pending reviewer confirmation.
