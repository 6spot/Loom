---
task: CI-GOV-T03
issue: 435
status: in_progress
depends_on: [CI-GOV-T02]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at:
completion_pr:
merge_sha:
---

# CI-GOV-T03 — Isolate Validator from routine core CI

## Scope

Validator is a staged/recertification tool, not semantic authority over ordinary product development. This task separates Validator-owned validation from routine core CI.

Core CI must validate production Rust, persistence, dependencies, deployment, and relevant non-Validator governance without compiling, linting, testing, documenting, or running Validator gates as a required part of ordinary product changes.

Validator-owned source/tools/ledgers move to a dedicated workflow that also supports explicit manual dispatch for staged validation. Historical full-certification tooling remains explicit and unchanged.

## Acceptance

- [ ] Core CI has no Validator route/job.
- [ ] Validator-only changes do not trigger routine core CI.
- [ ] Core check/clippy/tests/rustdoc exclude `loom-validator`.
- [ ] Core ledger validation does not inspect Validator/re-certification ledgers.
- [ ] Dedicated Validator workflow runs on Validator-owned changes.
- [ ] Dedicated Validator workflow supports `workflow_dispatch`.
- [ ] Full certification remains explicit and is not run routinely.
- [ ] No product or architecture semantics change.

## Progress Log

- 2026-08-30 — Started as dedicated CI governance issue #435 after confirming that a separate Validator job alone still left hidden coupling through workspace Rust checks and Validator-specific ledger checks.

## Verification Evidence

Pending delivery PR CI and merge evidence.
