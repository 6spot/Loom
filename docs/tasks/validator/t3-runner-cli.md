---
task: VAL-T3
issue: 255
status: in_progress
depends_on: ["VAL-T2"]
created_at: 2026-08-25
started_at: 2026-08-25
completed_at:
completion_pr:
merge_sha:
---
# VAL-T3 — Validator runner CLI and scenario selection

Define the deterministic command-line selection and execution behavior for the
public-consumer validator. Scenario metadata and results remain the stable
contracts from VAL-T2; the runner owns selection and ordering, while callers
provide the scenario executor.

## Acceptance

- [ ] `list`, single-ID, repeated-ID, and all-available selection work.
- [ ] Selected scenarios execute in registry ID order, independent of input
  order; repeated IDs are de-duplicated.
- [ ] Unknown or malformed IDs are runner/configuration errors and do not
  invoke any scenario executor.
- [ ] Normal development mode continues after a scenario returns `Fail` and
  collects the remaining selected results.
- [ ] Exit semantics are explicit and tested.
- [ ] Standard Rust gates pass.

## CLI contract

```text
loom-validator list
loom-validator run
loom-validator run CV-001 CV-002
loom-validator run --scenario CV-001 --scenario CV-002
loom-validator run --all
```

`run` is the default command and selects all registered scenarios when no IDs
are supplied. `--scenario` may be repeated or given comma-separated IDs.
Selection errors are reported on stderr with process status `2`.

Scenario outcomes are reported independently from runner/configuration errors.
Normal runs continue after `Fail` and return status `0`, so Task Ledger and
development feedback can collect every finding. `--nonzero` returns status `1`
when any scenario fails while still collecting later results. `--fail-fast`
stops after the first `Fail` and also returns status `1`.

## Progress log

- 2026-08-25 — Added typed runner selection, deterministic execution, separate
  configuration errors, concise report summaries, and dependency-free CLI
  parsing under GitHub issue #255.

## Verification Evidence

- `cargo fmt --all -- --check` → passed.
- `cargo check -p loom-validator --all-targets` → passed.
- `cargo test -p loom-validator` → 30 tests passed.
- `cargo clippy -p loom-validator --all-targets --all-features -- -D warnings`
  → passed.
- `cargo run -q -p loom-validator -- list` → empty registry listed with status
  `0`.
- `cargo run -q -p loom-validator -- run --scenario CV-001` → unknown ID
  reported as a configuration error with status `2`.

Acceptance remains pending reviewer confirmation.
