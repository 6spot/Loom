# Loom Agent Instructions

Read this file first. Keep it short.

## Required reading

Before acting on a Loom task, read the repository instructions relevant to the current work. Do not rely on memory or previous runs.

Always read:

- `AGENTS.md`;
- `docs/development/README.md`;
- `docs/tasks/README.md`;
- the current task record under `docs/tasks/`;
- the linked GitHub Issue;
- the current initiative or milestone `README.md` when one exists.

Before finishing an executable task with a Task Ledger record, also read and follow `docs/development/task-completion.md`.

For architecture-sensitive work, additionally read `docs/architecture/README.md` and every relevant accepted Amendment.

Repository canonical documents are the project authority. If a role prompt or previous-run assumption conflicts with the current repository procedure, do not silently follow the stale assumption; resolve the conflict against the canonical repository documents first.

## Task completion invariant

For every executable Loom task that has a record under `docs/tasks/`, a merged delivery PR is **not** completion.

Before the task may be reported complete, its GitHub Issue may be closed, or an external workflow may be marked done, the repository default branch must show all required completion evidence:

- task front matter has `status: completed`;
- `completed_at` is set;
- `completion_pr` is the actual delivery PR number;
- `merge_sha` is the actual default-branch merge commit for that delivery PR;
- every task acceptance checkbox that was satisfied by the delivered work is checked;
- verification / CI evidence is recorded;
- the initiative or milestone index agrees with the task record;
- applicable Task Ledger / governance checks pass.

If the real merge SHA is only available after the delivery PR merges, an immediate post-merge reconciliation change is required. The task remains incomplete until that reconciliation reaches the default branch and the canonical record is re-read and confirmed.

Do not close the GitHub Issue, mark Multica/external state done, or activate a dependent task from the delivery merge alone. Automation must schedule/continue the post-merge reconciliation instead of skipping it.

`docs/development/task-completion.md` contains the detailed operational procedure; the invariant above is mandatory even if that deeper guide is not otherwise needed for the current change.

## Before editing

- Read `docs/README.md` and follow the canonical document for the task.
- For architecture-sensitive changes, read `docs/architecture/README.md` and every relevant accepted Amendment.
- For implementation work, read the active task file under `docs/tasks/` and its linked GitHub Issue.
- Inspect the current code and tests before deciding what to change.
- Use the current procedure under `docs/development/` or `docs/deployment/`; do not invent a parallel workflow.

## While editing

- Stay inside the accepted task scope.
- Preserve architecture-owned authority, crate boundaries, dependency rules and public API boundaries.
- Do not create duplicate authority, API, initialization, persistence, deployment or test paths.
- Put operational instructions in the canonical development/deployment guide, not here.
- Keep task files as status/evidence records, not alternate specifications.
- Add or update tests at the layer that owns the changed contract.
- Do not weaken or skip a failing contract just to make tests pass.

## Stop and resolve first

Stop implementation if:

- the change requires a new semantic or authority decision;
- the task conflicts with the architecture authority map or an accepted Amendment;
- two current documents prescribe different procedures for the same workflow;
- completing the task requires changing its accepted scope or violating a documented boundary;
- the task is cancelled, superseded or replaced.

Architecture gaps go through the Amendment process in `docs/architecture/README.md`.

## Before finishing

- Run the checks required by the current CI and development guides.
- Do not claim checks passed unless they actually ran successfully.
- Record any unverified checks and the reason.
- Update the active task record with status and verification evidence.
- If the task has a canonical Task Ledger record under `docs/tasks/`, a merged delivery PR is not completion. Follow `docs/development/task-completion.md` and reconcile the canonical task record on the default branch with the actual PR/merge evidence before treating the task as complete.
- Keep the GitHub Issue and task record consistent.

## Maintain this file

Only add repository-wide instructions that apply to most tasks.

Do not add architecture summaries, runbooks, milestone status, copied documentation, or warnings about a single past mistake. Fix those at their canonical source instead.
