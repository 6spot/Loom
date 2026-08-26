---
task: VAL-T6
issue: 258
status: planned
depends_on: [257]
created_at: 2026-08-24
started_at:
completed_at:
completion_pr:
merge_sha:
---
# VAL-T6 — Task Ledger feedback bridge

Append concise validator observations to Loom's own task records while
preserving the task ledger as an append-only audit trail.

## Acceptance

- [ ] a synthetic failure appends exactly one durable finding to the intended
  task file;
- [ ] rerun/update behavior does not rewrite prior findings;
- [ ] raw logs are not inserted into task Markdown;
- [ ] missing/ambiguous target task is a feedback/config error rather than
  writing elsewhere;
- [ ] a passing scenario is recorded only when the task explicitly declares
  that scenario as a capability gate;
- [ ] standard Rust gates pass.

## Scope

- `RunMetadata` carries an explicit global task-record path or explicit
  scenario-to-record mappings. The feedback bridge never scans directories or
  derives a filename from a scenario ID.
- `RunMetadata` also carries the caller-supplied observation date and run ID;
  the run ID may be supplied by an explicit `run:` evidence reference when
  the dedicated field is unavailable.
- A task declares capability gates in front matter using `capability_gate` or
  `capability_gates`, or under a `## Capability Gates` section. A scenario ID
  in ordinary prose or in a previous feedback entry is not a gate declaration.
- Each appended block uses the stable `## Capability Validation` and
  `## Validation Findings` headings and only records scenario ID/name,
  outcome, expected, actual, backend/context, evidence, observation date and
  run reference. Individual fields are bounded and Markdown-safe.
- Existing bytes are never rewritten or removed. A later validator run adds a
  new block, including a later resolution if the original finding remains.

No Runtime/Storage authority, task-status mutation, filename discovery, raw
stdout/stderr ingestion, remediation policy, or report-file embedding is part
of this task.

## Progress Log

- 2026-08-25 — Added explicit task-record/run metadata to validator reports and
  an append-only feedback bridge with target/configuration errors, bounded
  Markdown rendering, and capability-gate pass handling.

## Verification Evidence

- `cargo fmt --all -- --check` → passed.
- `cargo test -p loom-validator --all-features` → passed (73 tests,
  including synthetic failure, append-only rerun, bounded raw-log handling,
  explicit gate pass, and missing/ambiguous target cases).
- `cargo clippy -p loom-validator --all-targets --all-features -- -D warnings`
  → passed.
- `cargo check --workspace --all-targets --all-features` → passed.
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` →
  passed.
- `cargo test --workspace --all-features` → passed, including the validator,
  Runtime, Storage, PostgreSQL contract, and composition suites.

Acceptance remains pending reviewer confirmation.
