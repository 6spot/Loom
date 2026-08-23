# Loom Agent Guide

`AGENTS.md` is the execution entry point for contributors and coding agents. It is **not** an architecture specification, project-status summary, operational runbook, or history of past mistakes.

## Source of truth

Start with [`docs/README.md`](docs/README.md). It routes each kind of question to the current canonical source:

- architecture, semantics, ownership and dependency boundaries → `docs/architecture/`;
- development and test procedures → `docs/development/`;
- deployment procedures → `docs/deployment/` when present;
- implementation plan, status and completion evidence → `docs/tasks/`.

Do not recover current requirements or commands from chat history, closed Issues, superseded task records, old documents, or an implementation that conflicts with the canonical documentation.

For architecture work, [`docs/architecture/README.md`](docs/architecture/README.md) defines document precedence, reverse supersession, accepted Amendments and deferred decisions. Resolve affected baseline clauses through that index before implementing them.

## Before you work

1. Read `docs/README.md` and locate the canonical documents for the task.
2. Identify the active task record and linked GitHub Issue when the work belongs to the V0 implementation plan.
3. Read the relevant architecture sources and all accepted Amendments that supersede affected clauses before changing semantics, public APIs, crate dependencies or authority boundaries.
4. Inspect the current code and tests before deciding what must change.
5. Use the current development or deployment guide for environment setup and operational commands instead of inventing a parallel procedure.

## Execution rules

- Implement the accepted task scope; do not turn implementation work into an implicit architecture redesign.
- Follow architecture-owned crate boundaries, dependency rules, public exposure rules and authority placement rather than moving responsibilities for convenience.
- Do not create a second authority path, API path, initialization path or operational workflow when the repository already defines one.
- When replacing a workflow or procedure, update the canonical guide and remove obsolete instructions instead of leaving competing alternatives.
- Keep implementation-specific details out of architecture documents unless they change the architecture contract.
- Keep operational commands out of `AGENTS.md`; they belong in the appropriate current guide under `docs/development/` or `docs/deployment/`.
- Keep task files as audit records, not scratchpads or alternate specifications.
- Add or update tests for behavior changes at the layer that owns the contract.
- Do not weaken, skip or rewrite a failing contract merely to make a task pass unless the canonical architecture explicitly requires that contract to change.

## Task lifecycle

Follow [`docs/tasks/README.md`](docs/tasks/README.md) for task state and evidence rules.

When implementation starts, keep the active task record in sync with the work. When work is blocked, record the blocker rather than silently changing scope. A task is complete only when its acceptance criteria and required verification pass and its completion evidence is recorded.

GitHub Issues are the collaboration surface; repository task files are the durable implementation audit trail. They must agree on the final state.

## Verification

Use the repository's current CI workflow and development guides as the source for required verification.

- Run the checks relevant to the changed code and contract.
- Run required integration tests against the documented test environment.
- Do not claim a check passed unless it was actually executed successfully.
- If a required check cannot be run, report exactly what is unverified and why.
- Keep CI configuration aligned with supported repository environments rather than adding disposable one-off workflows.

## Stop conditions

Stop implementation and resolve the source of truth before continuing when any of these occurs:

- the requested behavior requires a semantic or authority decision not covered by the current architecture;
- the active task conflicts with the architecture authority map or an accepted Amendment;
- two current documents prescribe different procedures for the same workflow;
- satisfying the task would require changing its accepted scope or violating a documented boundary;
- the task has been cancelled, superseded or replaced by a newer plan.

Architecture gaps are resolved through the Amendment process defined by `docs/architecture/README.md`, not by encoding a new decision directly in code or task prose.

## Maintaining this file

Keep `AGENTS.md` short and stable. Add a rule here only when it is a repository-wide execution rule that applies across tasks.

Do **not** append incident-specific warnings, architecture summaries, current milestone summaries, copied runbooks or reminders about one agent's previous mistake. Fix recurring problems at their source: the canonical document, repository script, test contract, CI configuration, or architecture rule that owns the behavior.
