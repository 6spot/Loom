# Loom Agent Instructions

Read this file first. Keep it short.

## Required reading

Before acting on a Loom task, read the repository instructions relevant to the current work. Do not rely on memory or previous runs.

Always read:

- `AGENTS.md`;
- `docs/development/README.md`.

When working inside a subtree that contains a more specific `AGENTS.md`, read that file as well. Subtree instructions may add application/module-specific rules but do not override repository architecture authority.

When a task or Issue points to planning material under `docs/tasks/`, read the relevant task note and initiative README for scope, ownership and historical context. Task notes are documentation, not the execution-state authority.

For architecture-sensitive work, additionally read `docs/architecture/README.md`, resolve the current authority through its reverse supersession table, and read every relevant accepted Amendment.

Repository canonical documents are the project authority for architecture and development procedure. If a role prompt or previous-run assumption conflicts with the current repository procedure, resolve the conflict against the canonical repository documents first.

## Execution and completion authority

Do not build a second workflow state machine out of Markdown files.

- GitHub Issues describe work and acceptance context.
- The active orchestrator owns execution state, dependency readiness and staged scheduling. When work is coordinated by Multica, Multica Issue state, dependencies and Stage relationships are authoritative for that workflow.
- GitHub PRs and required checks are the delivery/merge authority for repository changes.
- `docs/tasks/` may preserve planning, scope, ownership and useful evidence, but its `status`, `depends_on`, `completion_pr`, `merge_sha` or similar fields do not gate execution and do not override the active orchestrator.

A delivery does not require a post-merge Markdown reconciliation run merely to copy PR number, merge SHA or external workflow state back into a Task Ledger file.

If a task note is touched as part of the delivery, keep it accurate and useful, but do not create a follow-up PR solely to synchronize task-state metadata.

## Before editing

- Read `docs/README.md` and follow the canonical document for the task.
- For architecture-sensitive changes, read `docs/architecture/README.md` and every currently relevant accepted Amendment.
- Read the current Issue/task context and inspect the current code and tests before deciding what to change.
- Use the current procedure under `docs/development/` or `docs/deployment/`; do not invent a parallel workflow.

## While editing

- Stay inside the accepted task scope.
- Preserve architecture-owned authority, crate boundaries, dependency rules and public API boundaries.
- Do not create duplicate authority, API, initialization, persistence, deployment or test paths.
- Put operational instructions in the canonical development/deployment guide, not in task notes.
- Keep task notes as planning/evidence records, not alternate specifications or workflow state machines.
- Add or update tests at the layer that owns the changed contract.
- Do not weaken or skip a failing contract just to make tests pass.

## Stop and resolve first

Stop implementation if:

- the change requires a new semantic or authority decision;
- the task conflicts with the architecture authority map or an accepted Amendment;
- two current canonical documents prescribe different procedures for the same workflow;
- completing the task requires changing its accepted scope or violating a documented boundary;
- the task is cancelled, superseded or replaced by the active Issue/orchestrator.

Architecture gaps go through the Amendment process in `docs/architecture/README.md`.

A stale Task Ledger status by itself is not a reason to block work that the active orchestrator has made ready.

## Before finishing

- Run the focused checks required by the current CI/development/deployment guides for the changed contract.
- Do not claim checks passed unless they actually ran successfully.
- Record any unverified checks and the reason.
- Keep task documentation accurate when the current change already touches it, but do not require post-merge reconciliation solely for task-state bookkeeping.
- Keep the GitHub PR/Issue description consistent with the delivered work.

Repository delivery completion follows `docs/development/task-completion.md`.

## Maintain this file

Only add repository-wide instructions that apply to most tasks.

Do not add architecture summaries, runbooks, milestone status, copied documentation, CI matrices or warnings about a single past mistake. Fix those at their canonical source instead.
