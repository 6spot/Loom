---
task: VAL-T5
issue: 257
status: planned
depends_on: [255, 256]
created_at: 2026-08-24
started_at:
completed_at:
completion_pr:
merge_sha:
---
# VAL-T5 — Deterministic reports and durable evidence references

Emit concise machine-readable validator reports for CI, execution agents, and
Task Ledger feedback without copying raw diagnostics into Markdown task files.

## Acceptance

- [ ] equivalent scenario results serialize deterministically;
- [ ] report distinguishes scenario failure, prerequisite unavailable, and
  runner/config failure;
- [ ] report contains run metadata, selected scenario IDs, backend, result
  state, prerequisite details, and structured findings;
- [ ] evidence references can identify a command, run, artifact path, or CI
  reference;
- [ ] no suggested-remediation field is emitted by default;
- [ ] raw diagnostic output is retained separately and is not appended to task
  files;
- [ ] standard Rust gates pass.

## Scope

- `ValidationReport` owns the versioned canonical JSON schema and deterministic
  ordering of selected IDs, findings, prerequisite details, and evidence.
- `RunMetadata` and `EvidenceReference` carry explicit run/command/path/CI
  references suitable for a Task Ledger handoff.
- The CLI can write a machine-readable report only when an explicit
  `--json <PATH>` destination is supplied (`--report <PATH>` remains a
  compatibility alias); the human summary points to that artifact.
- Runner/configuration failures are represented without synthesizing a scenario
  finding. Raw logs and task-file mutation remain outside the validator.

No Runtime/Storage authority, remediation policy, automatic task-file update,
or raw-log ingestion is part of this task.

## Progress Log

- 2026-08-25 — Added the stable report schema, aggregate result-state
  classification, canonical serialization, Task Ledger evidence-reference
  helpers, explicit CLI report artifact output, and focused contract tests.
- 2026-08-25 — Extended the canonical artifact with deterministic `counts`,
  `run` policy/backend/selection metadata, and `results[]` fields for
  capability area, outcome, reason, expected/actual/context, and evidence.

## Verification Evidence

- `cargo fmt --all -- --check` → passed.
- `cargo check -p loom-validator --all-targets --all-features` → passed.
- `cargo test -p loom-validator --all-features` → passed (67 tests).
- `cargo run -q -p loom-validator -- --json ./validator-report.json` → wrote
  JSON report and pointed the summary at `path:./validator-report.json`; the
  temporary artifact was removed after inspection.

Acceptance remains pending reviewer confirmation.
