# Loom Agent Instructions

Read this file first. Keep it short.

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
- Keep the GitHub Issue and task record consistent.

## Maintain this file

Only add repository-wide instructions that apply to most tasks.

Do not add architecture summaries, runbooks, milestone status, copied documentation, or warnings about a single past mistake. Fix those at their canonical source instead.
