# Loom Task Ledger

This directory is the repository-level audit trail for Loom implementation work.

GitHub issues remain the collaboration surface for discussion, assignment and checklists. Task files preserve durable implementation status and completion evidence next to the code and architecture they describe.

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
task: M2-T1
issue: 26
status: planned
depends_on: []
created_at: 2026-08-21
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

## Progress log

Task files are audit records, not scratchpads. Keep a short append-only Progress Log for material transitions, architecture decisions, blockers and completion evidence. Do not rewrite earlier entries merely to make the history look cleaner.

## Milestone index

Each milestone directory contains a `README.md` that lists every task, dependency and status. The milestone index and child task files must agree before the milestone parent issue can close.
