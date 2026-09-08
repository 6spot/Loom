---
task: CI-GOV-T04
issue: 543
status: in_progress
depends_on: [CI-GOV-T03]
created_at: 2026-09-08
started_at: 2026-09-08
completed_at:
completion_pr:
merge_sha:
---

# CI-GOV-T04 — Retire completed Chronicle acceptance CI

## Scope

Issue #543 records the user's requested cleanup after C1-T17 completion. Retire the temporary T17 live-model workflow and disable its Actions registration together with the 20 stale registrations whose workflow files are absent from `main`. The issue records the exact 21 workflow IDs and paths.

Keep CI, Validator, Chronicle, Chronicle Docker and Multica CI Wakeup active. Preserve their workflow definitions, deterministic regression suites, explicit live-provider preflight scripts, historical Actions runs and all acceptance evidence. Update current Chronicle guides so the completed T17 workflow is no longer prescribed as a standing CI prerequisite.

No product, model, persistence, source-data or architecture behavior changes are included.

## Acceptance

- [x] The temporary T17 workflow definition and active documentation references are retired.
- [ ] All 21 obsolete Actions registrations are disabled; exactly the five supported workflows remain active.
- [x] Manual live extraction/presentation preflights and deterministic regression suites are retained.
- [ ] Historical acceptance run IDs and evidence remain accessible.
- [ ] Focused CI/governance checks pass and the task is reconciled on the default branch with real delivery evidence.

## Progress Log

- 2026-09-08 — Started after T17 delivery #535, reconciliation #542 and canonical completion/closure of #506 and Root #489. Inventory found 26 active Actions registrations: five supported workflows, one temporary T17 live-model workflow and 20 registrations with no workflow file on `main`. No open PR or queued/running Actions job uses the obsolete definitions. Cleanup is tracked separately from T17 under the CI governance boundary.
- 2026-09-08 — Removed the temporary T17 workflow definition and updated the two active acceptance/Reader guides to retain explicit live-provider preflights. The five supported workflow definitions, preflight scripts and deterministic regression tests are unchanged. The CI governance ledger check and all three READY-tool regression tests pass, as does whitespace validation. Actions registration retirement and final delivery/reconciliation evidence will be recorded after the cleanup PR merges.
