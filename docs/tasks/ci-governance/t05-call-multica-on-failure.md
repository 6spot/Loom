---
task: CI-GOV-T05
issue:
status: in_progress
depends_on: [CI-GOV-T04]
created_at: 2026-09-08
started_at: 2026-09-08
completed_at:
completion_pr:
merge_sha:
---

# CI-GOV-T05 — Call Multica only for opted-in CI failures

## Scope

The user requested removal of the standalone Multica wakeup runs created and
then skipped after ordinary CI completions. Replace the `workflow_run`
subscription with a reusable workflow called by CI, Validator, Chronicle and
Chronicle Docker after a failed check on a same-repository PR containing the
existing `Multica-Issue:` marker. Keep exact issue-key validation and re-read
the PR before sending, rejecting closed PRs and superseded heads.

This dedicated governance task changes notification routing only; existing
test jobs, path classification and required validation remain intact.

## Acceptance

- [x] The Multica definition exposes only `workflow_call`, removing its
  subscription to ordinary CI completions.
- [x] Each of the four callers covers all its check jobs and requires failure,
  an uncancelled run, a same-repository PR and the marker in its event payload.
- [x] Only a valid standalone `Multica-Issue: ME-<digits>` line on an open PR
  with the tested head permits the notification step.
- [x] Focused local workflow, notification and Task Ledger validation passes.
- [ ] Delivery review/CI, merge and default-branch reconciliation are recorded.

## Verification evidence

- `actionlint` 1.7.12 passed for all five changed workflow definitions.
- Local execution of the actual notification Bash steps passed 14 fixtures:
  valid keys, surrounding text, whitespace/CRLF, multiple keys, missing/null
  bodies, malformed/inline/multiline markers, trailing text, closed/merged
  PRs, superseded heads and shell-like input. GitHub and Multica commands were
  stubbed; no notification was sent. Payload fields and endpoint selection
  were checked for every accepted fixture.
- Parsed workflow comparison against `HEAD` confirmed all existing caller
  jobs, event triggers and path classifiers are unchanged and every check job
  is covered by the new caller's `needs` list.
- `python3 tools/test_validator_ready.py` passed all three tests.
- `python3 tools/validator_ready.py --root docs/tasks/ci-governance --check --format json`
  passed with five records and no violations.
- Scoped `git diff --check` passed. GitHub Actions execution and Code Owner
  review remain pending; the GitHub Issue and delivery PR have not been created.

## Progress Log

- 2026-09-08 — Started from `f603fb099c6d34a7dd51ee1c153634d3223ca8ba` after
  confirming CI-GOV-T04 is canonically completed. The latest 20 Multica Actions
  runs were all skipped; a sampled run had no executed steps. GitHub documents
  that `workflow_run` triggers regardless of the upstream conclusion.
- 2026-09-08 — Prepared and locally verified the reusable workflow and four
  failure-gated callers. Documented PR opt-in timing and check-job coverage in
  the developer guide. The task remains `in_progress` until delivery review,
  CI and canonical post-merge reconciliation are available.
