---
task: CI-GOV-T01
issue: 428
status: in_progress
depends_on: []
created_at: 2026-08-30
started_at: 2026-08-30
completed_at:
completion_pr: 429
merge_sha:
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

- [ ] Routine Validator CI runs the authority regression gate.
- [ ] Routine Validator CI runs `validator-certification-gate.py --regression-check`.
- [ ] Routine Validator CI does not run the no-argument full `validator-certification-gate.sh`.
- [ ] Routine CI does not upload `validator-t24-final-certification` artifacts.
- [ ] Historical T24 scripts, candidate fence and certification records remain intact.
- [ ] `.github/workflows/**` and scripts that directly define CI gate policy have Code Owner coverage.
- [ ] The CI classifier recognizes this governance ledger and validates CI-authority changes through the existing lanes.
- [ ] No production or architecture semantics change.

## Progress Log

- 2026-08-30 — Started after PR #426 exposed that the completed VALR-T24 fixed-candidate evidence fence was still present in routine development CI. The dedicated governance issue is #428; Scheduler discovery and Validator feature leaves remain unchanged.
- 2026-08-30 — Delivery PR #429 opened with only CI/governance files changed. The existing external Validator job/check name is retained for required-check compatibility while the internal lane becomes regression-only.

## Verification Evidence

Pending delivery PR CI and merge evidence.
