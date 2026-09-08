---
task: CI-GOV-T04
issue: 543
status: completed
depends_on: [CI-GOV-T03]
created_at: 2026-09-08
started_at: 2026-09-08
completed_at: 2026-09-08
completion_pr: 544
merge_sha: e4c2567a9f3ba17b20161285c3eb3c155cc5a1f6
---

# CI-GOV-T04 — Retire completed Chronicle acceptance CI

## Scope

Issue #543 records the user's requested cleanup after C1-T17 completion. Retire the temporary T17 live-model workflow and the 20 stale registrations whose workflow files are absent from `main`. The issue records the exact 21 workflow IDs and paths. GitHub marks the removed T17 workflow registration `deleted`; the other 20 are `disabled_manually`.

Keep CI, Validator, Chronicle, Chronicle Docker and Multica CI Wakeup active. Preserve their workflow definitions, deterministic regression suites, explicit live-provider preflight scripts, historical Actions runs and all acceptance evidence. Update current Chronicle guides so the completed T17 workflow is no longer prescribed as a standing CI prerequisite.

No product, model, persistence, source-data or architecture behavior changes are included.

## Acceptance

- [x] The temporary T17 workflow definition and active documentation references are retired.
- [x] All 21 obsolete Actions registrations are retired (20 disabled and one deleted); exactly the five supported workflows remain active.
- [x] Manual live extraction/presentation preflights and deterministic regression suites are retained.
- [x] Historical acceptance run IDs and evidence remain accessible.
- [x] Focused CI/governance checks pass and the task is reconciled on the default branch with real delivery evidence.

## Verification evidence

- Delivery PR [#544](https://github.com/6spot/Loom/pull/544) merged as `e4c2567a9f3ba17b20161285c3eb3c155cc5a1f6`; delivery head `51501d601b7cefc7fe816ece2e9c9b1c99dd99ac` passed [CI 34175151733](https://github.com/6spot/Loom/actions/runs/34175151733), including change classification and the Task Ledger/governance job. Unrelated lanes were skipped by the existing classifier.
- `python3 tools/validator_ready.py --root docs/tasks/ci-governance --check --format json`, all three tests in `tools/test_validator_ready.py`, and `git diff --check` passed. Focused review verified unchanged bytes for all five retained workflow definitions, both manual live-preflight scripts and the deterministic tests repeated by the retired workflow; Chronicle's existing test discovery still covers those tests.
- Actions readback confirmed 20 `disabled_manually` registrations, one `deleted` registration and exactly five active workflows: CI, Validator, Chronicle, Chronicle Docker and Multica CI Wakeup. No historical run was deleted. All eight T17 runtime/final-head CI run IDs remain accessible with their original successful conclusions and SHAs.
- Detailed inventory, state transitions, retained-surface checks and historical-run readbacks are archived under `/srv/loom-evidence/chronicle-c1-t17-r25-v7/ci-retirement/` and the matching local `.artifacts/c1-t17/r25-v7/ci-retirement/` directory.

## Progress Log

- 2026-09-08 — Started after T17 delivery #535, reconciliation #542 and canonical completion/closure of #506 and Root #489. Inventory found 26 active Actions registrations: five supported workflows, one temporary T17 live-model workflow and 20 registrations with no workflow file on `main`. No open PR or queued/running Actions job uses the obsolete definitions. Cleanup is tracked separately from T17 under the CI governance boundary.
- 2026-09-08 — Removed the temporary T17 workflow definition and updated the two active acceptance/Reader guides to retain explicit live-provider preflights. The five supported workflow definitions, preflight scripts and deterministic regression tests are unchanged. The CI governance ledger check and all three READY-tool regression tests pass, as does whitespace validation. Actions registration retirement and final delivery/reconciliation evidence will be recorded after the cleanup PR merges.
- 2026-09-08 — PR #544 merged after its required CI passed. Retired all 21 obsolete workflow registrations and re-read the resulting active set; GitHub automatically marked the removed live-model definition `deleted`, while the other 20 were disabled explicitly. All eight archived T17 runtime/final-head workflow records remain accessible. This post-merge reconciliation records the actual delivery merge evidence and completed checklist/index; Issue #543 closes only after the canonical default branch is re-read and the CI governance check passes.
