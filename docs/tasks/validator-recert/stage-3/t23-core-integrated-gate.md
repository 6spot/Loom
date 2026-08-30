---
task: VALR-T23
issue: 328
status: in_progress
depends_on: [327]
created_at: 2026-08-29
started_at: 2026-08-30
completed_at:
completion_pr:
merge_sha:
architecture_decision_blocker: false
---

# VALR-T23 — Current-main core integrated gate

## Candidate

T23 is being re-run against production candidate `02c55a6b5c34f227abfcb732a21bf6c390e22578`, the PR #393 merge that includes Architecture Amendment 0004 and the formal derived-resource read boundary.

The earlier T23 PASS on the pre-T27 candidate is historical input only. It cannot certify the new candidate by inheritance.

## Required evidence

The evidence-preparation PR containing this record must run the repository's normal required CI over a code-identical descendant of the production candidate:

- dependency/security policy
- architecture policy
- Validator authority gates
- Compose validation
- fmt
- workspace check
- strict workspace Clippy
- full `tools/test.sh --workspace --all-features`
- rustdoc with warnings denied
- complete PostgreSQL 18 persistence contract, including Validator lifecycle, replay/fork and T20 live matrix

The production candidate itself already has exact-tree implementation evidence from PR #393 run `33269628735`: the PR head and merge share Git tree `71bb8da37f55cc5b1bb4c8ed0f004f47a4ebf00e`. This T23 refresh additionally verifies the merged T22/ledger descendant before T24 is allowed to consume it.

## Acceptance

- [x] Production candidate is fixed to `02c55a6b5c34f227abfcb732a21bf6c390e22578`.
- [x] T22 represents exactly CV-001..CV-040 and records 40 ready / 0 gap.
- [x] CV-028/CV-029 rely on formal LoomClient observation and controlled setup only.
- [x] No old 38/2 result is promoted into current certification evidence.
- [x] Required commands are defined by repository CI.

Completion metadata remains intentionally empty until this refresh PR's required CI finishes and the PR is merged. T24 must not start from an unmerged T22/T23 evidence input.
