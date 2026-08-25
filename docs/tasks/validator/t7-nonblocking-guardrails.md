---
task: VAL-T7
issue: 259
status: in_progress
depends_on: [258]
created_at: 2026-08-24
started_at: 2026-08-25
completed_at:
completion_pr:
merge_sha:
---
# VAL-T7 — Enforce report-only feedback and no task-state mutation

Make the agreed observer-only behavior mechanically testable so future automation cannot quietly turn findings into remediation or task-state transitions.

## Acceptance

- [ ] failed validation leaves task metadata byte-for-byte unchanged;
- [ ] failed validation does not modify implementation/architecture files;
- [ ] append-only finding is preserved and subsequent unrelated work remains eligible;
- [ ] strict diagnostic mode changes exit behavior only, not mutation authority;
- [ ] standard Rust gates pass.

## Scope

- Feedback bridge is strictly observer-only / report-only. It may append concise `## Capability Validation` / `## Validation Findings` entries to an explicitly selected Task Ledger record, but it must never edit task frontmatter `status`, `started_at`/`completed_at`, `completion_pr`/`merge_sha`, acceptance checklist history, architecture documents, or implementation source as a reaction to a finding.
- The existing append-only invariant from VAL-T6 remains authoritative: existing bytes are never rewritten or removed; a later run adds a new block, including a later resolution if the original finding remains.
- Normal feedback mode records the failure and returns `Ok` so the outer recursive dispatcher can continue with unrelated READY leaves. It does not return an error that blocks the dispatcher and does not change its exit code.
- An explicit diagnostic/CI strict mode may return a nonzero exit code (`1` for scenario failure) for CI visibility, but it still cannot mutate task state, rewrite history, or apply fixes. The mode changes exit behavior only, not mutation authority.
- Regression tests around representative task files prove that only the allowed append-only validation section changes; protected regions remain byte-identical.

Remediation is out of scope for the validator. Any fix, task-state transition, or architecture change requires a separately planned task or accepted Architecture Amendment. The validator never applies remediation automatically.

No Runtime/Storage authority, filename discovery, raw stdout/stderr ingestion, or dual-write recovery is part of this task.

## Authority Boundary

The validator is an observer. It lacks authority to change `status`, timestamps, PR/SHA, acceptance history, or architecture/implementation content. Findings are factual observations (`scenario ID/name`, `expected`, `actual`, `backend/context`, `evidence`, `observation date`, `run reference`) rendered with bounded, Markdown-safe fields. Future automation must keep this boundary; guard tests fail if any protected field is rewritten.

## Remediation Policy

Validator findings do not imply remediation. If a finding requires code or architecture change, file a separate planned task (or Amendment for semantic/authority changes) that references the finding's scenario ID, evidence, and run reference. Do not edit the task file's status or history in place as a side effect of the validator run.

## Progress Log

- 2026-08-25 — Added report-only guardrails: observer-only documentation, append-only invariant enforcement, normal vs strict exit semantics, representative task-file regression tests, and implementation/architecture non-mutation coverage.

## Verification Evidence

- `cargo fmt --all -- --check` → passed.
- `cargo test -p loom-validator --all-features` → passed (including failed-validation metadata unchanged, implementation/architecture non-mutation, append-only preservation with unrelated work eligible, and strict-mode exit-only coverage).
- `cargo clippy -p loom-validator --all-targets --all-features -- -D warnings` → passed.
- `cargo check --workspace --all-targets --all-features` → passed.
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` → passed.
- `cargo test --workspace --all-features` → passed, including validator, Runtime, Storage, PostgreSQL contract, and composition suites.

Acceptance remains pending reviewer confirmation.
