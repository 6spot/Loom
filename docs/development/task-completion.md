# Loom task completion workflow

This guide defines repository delivery completion for executable Loom work.

The repository does not use Markdown Task Ledger state as a second workflow engine. Execution state, dependency readiness and staged scheduling belong to the active orchestrator; repository completion is based on the actual delivered change and its required verification.

## Completion sequence

For a repository change, use this sequence:

```text
implementation complete
        ↓
required focused verification passed
        ↓
required review passed
        ↓
required CI/checks passed
        ↓
delivery PR merged
        ↓
repository delivery complete
```

Do not create a post-merge reconciliation run or ledger-only PR merely to copy the final PR number, merge SHA, Issue state or external workflow state into Markdown.

## Task notes under docs/tasks

Task notes are optional planning and audit material. They may record:

- scope and file ownership;
- architecture/contract links;
- acceptance examples;
- useful verification evidence;
- historical decisions or implementation notes.

Legacy task files may also contain fields such as:

```yaml
status:
depends_on:
started_at:
completed_at:
completion_pr:
merge_sha:
```

Those fields are informational unless a task explicitly defines a product/runtime contract that consumes them. They are not repository-wide execution gates and must not override the active orchestrator.

If a delivery already edits a task note, keep the note accurate. Prefer recording useful evidence in the delivery PR itself. Do not require a follow-up change solely because final merge metadata was unknowable before merge.

## Dependency readiness

Repository Markdown does not decide whether another task may start.

When Multica coordinates the work, Multica Issue dependencies, parent/child relationships and Stage state are the scheduling authority. A stale `status` or `depends_on` value in `docs/tasks/` does not block an Issue that Multica has made ready.

Task-document dependency graphs remain useful design context and should still describe intended sequencing, but they are not a second scheduler.

## Verification

Run the checks appropriate to the changed contract. The current development guide and CI workflows are the source for those checks.

Do not:

- claim a check passed without running it;
- weaken a failing architecture/product contract just to finish a task;
- run unrelated full suites merely to satisfy historical Task Ledger ceremony.

If verification cannot be performed, record the missing verification and reason in the delivery handoff.

## GitHub Issues and external workflow state

GitHub Issue and external-orchestrator completion follow their own configured lifecycle. They do not wait for a Markdown reconciliation step that exists only to duplicate state.

For Multica-linked PRs, the repository/GitHub integration may close the corresponding Multica Issue after the qualifying PR merges. That merge-driven lifecycle does not require a second Task Ledger completion commit.

## Historical records

Existing Task Ledger reconciliation PRs and completed metadata remain valid historical evidence of how earlier work was delivered. This guide does not require rewriting history or removing those records.

For new work, avoid introducing another durable status field when GitHub/Multica already owns that state.
