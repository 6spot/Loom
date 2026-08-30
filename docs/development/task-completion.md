# Loom task completion workflow

This guide is the canonical operational procedure for finishing an executable Loom task that has a durable Task Ledger record under `docs/tasks/`.

A merged delivery PR is not task completion. Completion is reached only after the canonical Task Ledger on the repository default branch has been reconciled with the real merge evidence and the repository-level completion checks pass.

## Completion sequence

Use this sequence for every executable task with a Task Ledger record:

```text
implementation complete
        ↓
required review passed
        ↓
required CI/checks passed
        ↓
delivery PR merged
        ↓
read the real delivery PR number and merge SHA
        ↓
reconcile the canonical Task Ledger on the default branch
        ↓
run the applicable ledger/governance checks
        ↓
merge any required ledger-only reconciliation PR
        ↓
re-read the canonical default branch and confirm the task record is completed
        ↓
close the GitHub Issue as completed
        ↓
mark any external workflow/task state complete
```

Do not reorder the final steps. In particular, do not close the GitHub Issue or mark an external workflow complete while the canonical Task Ledger is still stale.

## Canonical reconciliation

After the delivery PR is merged, obtain the actual merged PR number and actual merge commit SHA from the repository. Do not guess either value and do not copy an implementation-head SHA into `merge_sha`.

Update the task record required by `docs/tasks/README.md`. When the standard front matter is used, the completed record must include:

```yaml
status: completed
completed_at: YYYY-MM-DD
completion_pr: <actual delivery PR number>
merge_sha: <actual integration/default-branch merge SHA>
```

Also reconcile every task-local completion field required by the record and initiative, including as applicable:

- acceptance checklist state;
- verification / CI evidence;
- progress-log completion entry;
- milestone or initiative README status;
- dependency/READY eligibility derived from the canonical ledger;
- any other durable completion metadata required by the active task contract.

A feature branch, local worktree, agent comment, GitHub Issue state, PR state, or external task state is not the canonical ledger.

## Reconciliation write path

Prefer recording completion evidence in the delivery PR when every required value is already known.

When the final merge SHA only exists after merge, perform an immediate small follow-up audit change. Use the normal repository contribution path. If repository policy requires a PR, create a ledger-only reconciliation PR, run its required checks, merge it, and then re-read the default branch.

The reconciliation change must not silently absorb new implementation scope. If new product or architecture work is required, reopen or create the appropriate executable task instead.

## Verification

Run the Task Ledger / governance checks applicable to the changed initiative. For ledgers covered by the repository validator, use the current commands documented by the initiative and CI, including `tools/validator_ready.py` where applicable.

A task is not complete while its canonical ledger fails a required governance check.

## Dependency eligibility

Downstream READY eligibility must be computed from the reconciled canonical ledger, not from:

- a merged delivery PR alone;
- a closed GitHub Issue alone;
- an agent saying the task is complete;
- Multica or another external workflow status;
- a task record that exists only on a feature branch.

If a downstream task depends on the current task being `completed`, do not activate it until the canonical record on the default branch actually reflects completion.

## Agent / automation rule

Agents and automation working in Loom must read `AGENTS.md`, this guide, `docs/tasks/README.md`, the current task record, and the initiative README before finishing an executable task.

Automation may split implementation and post-merge reconciliation into separate runs, but the task remains incomplete between those runs. If reconciliation needs a repository edit, the responsible implementation agent performs that edit; a coordination-only agent must dispatch it rather than skipping the gate.

## Completion invariant

The invariant is:

```text
delivery PR merged != task completed

canonical task record reconciled on the default branch
+ required ledger/governance checks passed
= repository completion gate satisfied
```

Only after that gate is satisfied may external tracking state be finalized.
