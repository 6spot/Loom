# Agent task-ledger workflow

Use this guide when the requested work has a record under `docs/tasks/` or a linked executable GitHub Issue.

The canonical state model remains `docs/tasks/README.md`. The canonical completion sequence remains `docs/development/task-completion.md`.

## 1. Before implementation

Read:

- `docs/tasks/README.md`;
- the current initiative/milestone `README.md` when one exists;
- the concrete task file;
- the linked GitHub Issue;
- `docs/development/task-completion.md`.

Verify:

- the task is executable rather than a coordination tracker;
- dependencies are complete on the default branch;
- the task is not cancelled or superseded;
- Issue and task scope agree;
- architecture authority still supports the planned implementation.

Do not activate work because a dependency merely has a merged delivery PR. Use the canonical task state required by the repository procedure.

## 2. While implementing

Stay inside the accepted task scope.

Keep the task record as an audit record rather than a scratchpad or replacement specification. Record only material status/evidence transitions required by the current ledger procedure.

If implementation requires a new semantic or authority decision, stop the implementation path and use the Architecture Amendment procedure rather than expanding the task implicitly.

## 3. Verification evidence

Record only evidence that actually exists.

Include the focused checks relevant to the task and identify anything not run or blocked. Do not copy old CI evidence from another commit as proof for the current change.

## 4. Delivery merge is not completion

For Loom executable tasks:

```text
delivery PR merged
!=
task complete
```

Completion is governed by the canonical record on the default branch.

When the actual delivery merge SHA is only known after merge, perform the required post-merge reconciliation described in `docs/development/task-completion.md`.

Do not close the Issue, mark an external workflow done or activate dependent work until the repository's completion invariant is satisfied.

## 5. Keep Issue and ledger consistent

GitHub Issue:

- discussion;
- assignment;
- collaboration/checklists.

Task file:

- durable scope/dependency/status/evidence record.

They should describe the same real state. Neither an Agent message nor an external tracker overrides the canonical task record on the default branch.

## 6. Completion report

For task-backed work, report:

- what changed;
- which task/authority owned it;
- exact verification performed;
- what remains unverified, if anything;
- current PR/Issue/task-ledger state;
- whether post-merge reconciliation is still required.

Do not claim `completed` while the canonical default-branch record still says otherwise.