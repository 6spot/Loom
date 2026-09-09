# Loom Agent Instructions

Read this file first. Keep it short.

## Required reading

Before acting on a Loom task, read the repository instructions relevant to the current work. Do not rely on memory or previous runs.

Always read:

- `AGENTS.md`;
- `docs/development/README.md`.

When working inside a subtree that contains a more specific `AGENTS.md`, read that file as well. Subtree instructions may add application/module-specific rules but do not override repository architecture authority.

When a task or Issue links to material under `docs/tasks/`, read the relevant task note and initiative README for scope, ownership, dependencies and historical context.

For architecture-sensitive work, additionally read `docs/architecture/README.md`, resolve the current authority through its reverse supersession table, and read every relevant accepted Amendment.

Repository canonical documents are the project authority for architecture and development procedure. If a role prompt or previous-run assumption conflicts with the current repository procedure, resolve the conflict against the canonical repository documents first.

## Task context

GitHub Issues carry the task goal and acceptance context. Repository task notes may preserve planning, file ownership, dependency diagrams and useful implementation evidence. GitHub PRs carry the delivered repository change and its review/check results.

Task-note metadata is descriptive context. When a task is assigned for implementation, use the current task and Issue as the work to execute, and use linked task notes to understand its boundaries and prerequisites.

The standard delivery flow does not include a separate post-merge bookkeeping change solely to copy final PR or merge metadata into task notes.

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
- Keep task notes as planning/evidence records, not alternate specifications.
- Add or update tests at the layer that owns the changed contract.
- Do not weaken or skip a failing contract just to make tests pass.

## Stop and resolve first

Stop implementation if:

- the change requires a new semantic or authority decision;
- the task conflicts with the architecture authority map or an accepted Amendment;
- two current canonical documents prescribe different procedures for the same workflow;
- completing the task requires changing its accepted scope or violating a documented boundary;
- the task is cancelled, superseded or replaced.

Architecture gaps go through the Amendment process in `docs/architecture/README.md`.

## Before finishing

- Run the focused checks required by the current CI/development/deployment guides for the changed contract.
- Do not claim checks passed unless they actually ran successfully.
- Record any unverified checks and the reason.
- Keep task documentation accurate when the current delivery already touches it.
- Keep the GitHub PR/Issue description consistent with the delivered work.

Repository delivery completion follows `docs/development/task-completion.md`.

## Maintain this file

Only add repository-wide instructions that apply to most tasks.

Do not add architecture summaries, runbooks, milestone status, copied documentation, CI matrices or warnings about a single past mistake. Fix those at their canonical source instead.
