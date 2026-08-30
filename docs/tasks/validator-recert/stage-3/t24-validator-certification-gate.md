---
task: VALR-T24
issue: 329
status: in_progress
depends_on: [327]
created_at: 2026-08-27
started_at: 2026-08-30
completed_at:
completion_pr:
merge_sha:
architecture_decision_blocker: false
---

# VALR-T24 — Final Validator certification gate

## Purpose

T24 is being re-executed against production candidate `02c55a6b5c34f227abfcb732a21bf6c390e22578`. The prior T24 run on `103a75e96cd9f7b9e495a39bb6608316c47b76e6` remains historical: it truthfully produced 38 Pass / 2 Unavailable before Architecture Amendment 0004 and T27 closed the two formal-observation gaps.

This refresh does not change production semantics or acceptance criteria. It consumes the T22 manifest already merged by PR #394 and independently executes the named Validator targets plus the PostgreSQL 18 live gate.

## Candidate discipline

The gate keeps `02c55a6b5c34f227abfcb732a21bf6c390e22578` fixed as the production candidate. An evidence descendant is accepted only when:

- the candidate is an ancestor of the executed HEAD; and
- every candidate-to-HEAD change is documentation, the CI workflow, or the T24 certification-gate tooling itself.

Any Rust, SQL, schema, Runtime, Storage, Validator scenario, capability or other production change fails before certification tests execute.

## Required result

`bash tools/validator-certification-gate.sh` must:

- read T22 from merged main rather than from an unmerged manifest edit;
- find exactly CV-001 through CV-040, duplicate-free;
- execute every named Validator/public-consumer target with nonzero real test summaries;
- execute the repository-managed PostgreSQL 18 live gate;
- preserve backend/restart/required-live negative checks;
- classify every CV as Pass only from an actually executed passing suite;
- write `target/validator/t24-validator-certification-gate.json`;
- report `40 Pass`, `0 Unavailable`, `0 gap`, and `gate_passes=true`.

CV-028/CV-029 are not generic-registry scenarios. Their certification source is the controlled `semantic_blob` suite: setup/fault injection may use Runtime/ProjectionStore/BlobStore, while the capability observations themselves use the formal LoomClient semantic/blob read boundary.

## Governance hardening

This refresh also adds a CI invariant for the complete `docs/tasks/validator-recert` Task Graph. Stage-2/Stage-3 metadata may no longer be invalid while ordinary CI remains green.

## Acceptance

- [x] T22 is merged and records 40 ready / 0 gap for the fixed production candidate.
- [x] T23 is completed from PR #394 core/PG18 evidence on an evidence-only descendant.
- [x] T24 tooling is fail-closed on production-changing descendants.
- [x] Full recert Task Ledger validation is wired into CI.
- [ ] T24 certification report contains exactly 40 Pass and `gate_passes=true`.
- [ ] All underlying commands execute real tests with no failed or zero-test summary.
- [ ] Required CI, including PostgreSQL 18, completes successfully on this exact PR head.
- [ ] Completion metadata is populated only after the T24 PR merges.
