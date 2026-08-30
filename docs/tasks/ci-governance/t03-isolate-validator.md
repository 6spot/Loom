---
task: CI-GOV-T03
issue: 435
status: completed
depends_on: [CI-GOV-T02]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at: 2026-08-30
completion_pr: 437
merge_sha: 7c8316a2a76beab00aaee5e2aa803f88e600bd05
---

# CI-GOV-T03 — Isolate Validator from routine core CI

## Scope

Validator is a staged/recertification tool, not semantic authority over ordinary product development. This task separates Validator-owned validation from routine core CI.

Core CI validates production Rust, persistence, dependencies, deployment, and relevant non-Validator governance without compiling, linting, testing, documenting, or running Validator gates as part of ordinary product changes.

Validator-owned source/tools/ledgers live in a dedicated workflow that also supports explicit manual dispatch for staged validation. Historical full-certification tooling remains explicit and unchanged.

## Acceptance

- [x] Core CI has no Validator route/job.
- [x] Validator-only source paths are excluded from routine core CI triggering.
- [x] Core check/clippy/tests/rustdoc exclude `loom-validator`.
- [x] Core ledger validation does not inspect Validator/re-certification ledgers.
- [x] Dedicated Validator workflow runs on Validator-owned changes.
- [x] Dedicated Validator workflow supports `workflow_dispatch`.
- [x] Full certification remains explicit and is not run routinely.
- [x] No product or architecture semantics change.

## Progress Log

- 2026-08-30 — Started as dedicated CI governance issue #435 after confirming that a separate Validator job alone still left hidden coupling through workspace Rust checks and Validator-specific ledger checks.
- 2026-08-30 — Added `.github/workflows/validator.yml`; removed Validator routing/job and Validator workspace participation from routine `.github/workflows/ci.yml`.
- 2026-08-30 — PR #437 passed both the core CI workflow and the new independent Validator workflow, then merged as `7c8316a2a76beab00aaee5e2aa803f88e600bd05`.

## Verification Evidence

Delivery PR #437 produced two independent successful workflow runs:

- Core CI run `33309570883` — PASS: classification, task-ledger governance, dependency/security, Rust checks, PostgreSQL 18 persistence contract, and Compose/deployment. The core job set contained no Validator job; Rust check/clippy/tests/rustdoc excluded `loom-validator`.
- Validator run `33309570904` — PASS: Validator change classification, Validator task ledgers, `cargo check -p loom-validator`, Validator clippy, unit tests, Rustdoc, authority regression gate, and T24 certification-tool regression.

The dedicated Validator workflow has `workflow_dispatch` for explicit staged validation. It does not run the no-argument full T24 certification. No Runtime, Storage, Scheduler, API, schema, SQL, dependency, or architecture semantic files changed.
