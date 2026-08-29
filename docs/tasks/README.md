# Loom Task Ledger

This directory is the repository-level audit trail for Loom implementation work.

GitHub issues remain the collaboration surface for discussion, assignment and checklists. Task files preserve durable implementation status and completion evidence next to the code and architecture they describe.

## V0 implementation history and current certification

The post-Amendment V0 roadmap is [`v0-roadmap.md`](v0-roadmap.md), covering the M4–M13 implementation history and GitHub issues #136–#203. It is an audit record of that delivery history, not a current certification claim.

Milestones 1–3 remain historical completed implementation baselines. The old unmerged M4–M13 planning in issues #60–#134 / draft PR #135 is superseded and must not be used as the current execution plan.

Current-main V0 re-certification is tracked separately in the [`validator-recert/README.md`](validator-recert/README.md) initiative. It includes the post-M13 authority-fix history and current Stage-3 gates; re-certification remains in progress and pending until T25. The repository must not be described as V0 re-certified or as having a complete recertification root before T25.

Actual current `main` and the current T20 evidence baseline are
`103a75e96cd9f7b9e495a39bb6608316c47b76e6`, the PR #384 merge. The post-
rollback lineage is PR #382 merge `a898e5be6e33f5f448992c7ddb642af7336bc8f8`,
PR #383 merge `7e92033c5b3a14ea30ad8b18bbc68f73145866bb`, then PR #384; T20
records 10/10 trusted PostgreSQL 18 rows on this baseline. T22's existing
manifest is under parallel current-main re-review, while T23/T24/T25 have no
current-main evidence on `103a75e…` yet. The former PR #381 reconciliation,
candidate `4efb1d346c926f2ee10654c3bc24cd92af351881`, snapshot/base
`6da9989eb9298aa9739a6aa681fbdb8cd9dcde4d`, prior actual-main
`ef281f886480663a94193f738179d14933040a12` and their T20/T22/T23/T24 results
remain historical/superseded. T19 remains a historical 32-ID registry
snapshot; prior CV gaps and `31 Pass / 9 Unavailable` /
`gate_passes: false` records remain historical. None of these records
certifies V0; re-certification remains pending until T25.

## Cross-cutting validator initiative

The first-party public-consumer validator is tracked in the
[`validator/README.md`](validator/README.md) initiative index. Its individual
implementation tasks continue to follow the same one-task/one-file audit rule;
the initiative index does not replace a task record. That historical Validator
ledger remains separate from the current-main `validator-recert` initiative and
is not marked complete by the existence of the latter.

Before implementing any planned task:

1. read `docs/architecture/README.md`;
2. resolve the reverse supersession table for every architecture clause used by the task;
3. read the task file and linked GitHub Issue;
4. if the implementation would require a new authority/semantic decision, stop and create an Architecture Amendment rather than deciding it inside the implementation task.

## One task, one file

Every implementation task must have one Markdown file under `docs/tasks/<milestone>/`.

Use stable task slugs rather than branch names so the record survives rebases, PR closure and future tooling changes.

## Status values

Each task file begins with metadata containing exactly one of these statuses:

- `planned` — accepted work that has not started;
- `in_progress` — implementation or review is active;
- `blocked` — work cannot proceed; the file must explain the blocker;
- `completed` — acceptance criteria passed and completion evidence is recorded;
- `cancelled` — intentionally stopped; the file must explain why and reference the superseding decision/task when applicable.

## Required metadata

```yaml
---
task: M4-T1
issue: 146
status: planned
depends_on: []
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
```

Dates use `YYYY-MM-DD`. `completion_pr` is the GitHub PR number. `merge_sha` is the commit on the integration branch that contains the completed work.

## State transition rules

### Starting work

When implementation begins, update the task file in the implementation branch/PR:

- `status: in_progress`;
- set `started_at`;
- append a short Progress Log entry describing the chosen implementation scope if it differs from the original plan.

### Blocking work

When work is materially blocked:

- set `status: blocked`;
- add the blocker, owner/dependency and what would unblock it to the Progress Log;
- keep the GitHub issue open unless the work is explicitly cancelled or superseded.

### Completing work

A task is not complete merely because code was merged or an issue was closed. Completion requires all of the following:

1. acceptance checklist in the task file is satisfied;
2. `status: completed`;
3. `completed_at` is set;
4. `completion_pr` is recorded;
5. `merge_sha` is recorded;
6. verification evidence records the relevant architecture/build/test/CI gates;
7. the GitHub issue is closed as completed and its checklist agrees with the task file.

Prefer updating the task record in the completion PR. If the final merge SHA only exists after merge, add it immediately in a small follow-up audit commit/PR; do not leave the field permanently blank.

### Cancellation / duplication

Do not mark cancelled or duplicate work as completed. Record why it stopped and identify the replacement task/issue.

For a superseded planning task, close the GitHub Issue as `not_planned` and either mark a merged task file `cancelled` with its replacement reference or, when the task file never reached `main`, keep the supersession record in the current roadmap/Issue history rather than importing obsolete task files merely to cancel them.

## Progress log

Task files are audit records, not scratchpads. Keep a short append-only Progress Log for material transitions, architecture decisions, blockers and completion evidence. Do not rewrite earlier entries merely to make the history look cleaner.

## Milestone index

Each milestone directory contains a `README.md` that lists every task, dependency and status. The milestone index and child task files must agree before the milestone parent issue can close.
