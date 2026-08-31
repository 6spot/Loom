# Loom Agent Guides

This directory is the operational entry point for coding, review, planning and documentation agents working in the Loom repository.

`AGENTS.md` remains the short repository-wide guardrail. These guides explain the execution workflow without becoming another architecture specification.

## Read in this order

1. [`../../AGENTS.md`](../../AGENTS.md) — mandatory repository-wide guardrails.
2. [`authority-and-scope.md`](authority-and-scope.md) — how to find current authority, classify work and choose the owning layer.
3. [`implementation-workflow.md`](implementation-workflow.md) — inspect/edit/review loop for implementation and documentation changes.
4. [`verification.md`](verification.md) — how to choose proportionate local checks and interpret CI routing.
5. [`task-ledger.md`](task-ledger.md) — executable task, Issue and post-merge completion workflow.

Then follow the canonical documents for the concrete task:

- architecture: `docs/architecture/README.md` and the current authority it resolves;
- development/testing: `docs/development/README.md`;
- deployment: `docs/deployment/README.md`;
- task audit trail: `docs/tasks/README.md` and the active task record when one exists.

## Scope

These files describe **how an Agent should work**. They must not copy or redefine Loom semantics, dependency rules, deployment commands or milestone state that already have a canonical owner.

When Loom evolves, prefer updating the canonical architecture/development/deployment source and keeping these guides as navigation and procedure.