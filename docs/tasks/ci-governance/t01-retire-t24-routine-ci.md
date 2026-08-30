---
task: CI-GOV-T01
issue: 428
status: completed
depends_on: []
created_at: 2026-08-30
started_at: 2026-08-30
completed_at: 2026-08-30
completion_pr: 429
merge_sha: 4bb186377caf0079262ea004334a3426797143f4
---

# CI-GOV-T01 — Retire completed T24 full certification from routine CI

## Scope

Correct the repository CI authority boundary after the completed Validator re-certification initiative.

This task may change only repository-governance surfaces needed to:

- keep ordinary Validator authority/regression validation;
- retain the T24 certification tool contract regression check;
- stop routine development CI from re-running the historical fixed-candidate VALR-T24 full certification;
- stop routine development CI from publishing a T24 final-certification artifact;
- establish explicit Code Owner coverage over CI workflow and directly-invoked gate-policy scripts.

Runtime, Storage, Scheduler, API, capability semantics, architecture clauses, the certified candidate, historical certificate/evidence and T24's explicit/manual certification semantics are out of scope.

## Authority boundary

Repository CI governance owns merge-gate policy. Product and architecture work execute under those gates. Validator regression observes capability contracts but does not become semantic or architectural authority over future product work.

A completed fixed-candidate certification may remain as a reproducible explicit tool, but its evidence-only descendant fence must not be applied automatically to ordinary future development.

## Acceptance

- [x] Routine Validator CI runs the authority regression gate.
- [x] Routine Validator CI runs `validator-certification-gate.py --regression-check`.
- [x] Routine Validator CI does not run the no-argument full `validator-certification-gate.sh`.
- [x] Routine CI does not upload `validator-t24-final-certification` artifacts.
- [x] Historical T24 scripts, candidate fence and certification records remain intact.
- [x] `.github/workflows/**` and scripts that directly define CI gate policy have Code Owner coverage.
- [x] The CI classifier recognizes this governance ledger and validates CI-authority changes through the existing lanes.
- [x] No production or architecture semantics change.

## Progress Log

- 2026-08-30 — Started after PR #426 exposed that the completed VALR-T24 fixed-candidate evidence fence was still present in routine development CI. The dedicated governance issue is #428; Scheduler discovery and Validator feature leaves remain unchanged.
- 2026-08-30 — Delivery PR #429 opened with only CI/governance files changed. The existing external Validator job/check name is retained for required-check compatibility while the internal lane becomes regression-only.
- 2026-08-30 — PR #429 passed every CI route and merged as `4bb186377caf0079262ea004334a3426797143f4`.

## Verification Evidence

PR #429 CI run `33308723218` passed all routed jobs:

- change classification;
- task-ledger governance, including the new CI governance ledger;
- dependency and security policy;
- Rust architecture/fmt/check/clippy/unit/Rustdoc lane;
- PostgreSQL 18 persistence contract lane;
- Loom server Compose config lane;
- Validator authority regression gate;
- Validator T24 certification-tool `--regression-check`.

The Validator lane contained no no-argument full T24 certification step and produced no routine T24 final-certification artifact. The delivery diff changed only `.github/CODEOWNERS`, `.github/workflows/ci.yml`, and the CI governance task records; no production or architecture semantic files changed.
