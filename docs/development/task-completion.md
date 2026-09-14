# Loom task completion workflow

This guide describes the standard repository delivery path for executable Loom work.

Requests limited to analysis, review or advice end with the requested report. If the user explicitly limits delivery to local changes or a draft PR, stop at that boundary and report the actual state; do not call it merged repository delivery.

## Completion sequence

```text
implementation complete
        ↓
focused verification passed
        ↓
required review passed
        ↓
required CI/checks passed
        ↓
delivery PR merged
        ↓
repository delivery complete
```

Task-specific acceptance may require additional product, data, browser or environment validation. Those checks belong to the task and its referenced development procedure.

## Delivery record

The GitHub Issue carries the task goal and acceptance context. The delivery PR carries the implementation change, review discussion and CI/check results.

Material under `docs/tasks/` may complement that record with:

- scope and file ownership;
- architecture or contract links;
- dependency/design diagrams;
- acceptance examples;
- useful verification evidence;
- implementation history.

When a task note is already part of the delivery, update useful evidence there as part of the same PR. Final PR numbers or merge SHAs may be recorded later when they are useful historical information, but they are not a separate required delivery phase.

## Verification

Choose verification based on the changed contract and the current development/deployment guides.

| Changed surface | Verification to select |
| --- | --- |
| Documentation or Agent instructions only | Review the changed rules for consistency, check local links and verify changed command examples against their owning scripts/configuration. Application builds and runtime suites are not added solely because a guide lists them. |
| Code, configuration or build output | Run the checks that exercise the changed behavior and its callers, using the owning module's guide. Shared code changes include affected consumers. |
| Database, service, browser or deployment behavior | Include the corresponding real-environment checks from the owning development/deployment guide. A stubbed or component-only result does not replace a required integration check. |

Combine matching rows. A task's explicit acceptance requirements still apply, including verification of runnable examples when those examples are the changed behavior.

- Run the focused tests, builds and static checks that exercise the modified behavior.
- Use the repository's real integration environment when the task requires database, service, browser or deployment behavior.
- Record checks that could not be run and why.
- A successful unrelated suite does not substitute for verification of the changed contract.

For each check, record the command, result, tested revision/worktree state and relevant environment in the delivery evidence. Reuse a successful result within the task when those inputs are unchanged. Re-run affected checks after code, dependencies, configuration or test data/environment changes, after a failure is fixed, or when a new finding calls that result into question. Continuation, self-review and committing unchanged tested content are not by themselves reasons to repeat a suite. Do not use an older success to hide a current failure.

The current CI workflows and repository merge rules remain the source for required checks. Local result reuse does not skip or waive CI required for the delivery revision.

## Review

Every delivered change receives self-review of the final diff, task scope, behavior, verification evidence and document consistency.

Independent review is required when the user/task, the applicable canonical workflow or repository merge rules require it. Follow the specified reviewer and completion conditions. Without such a requirement, self-review satisfies the review stage; do not add another model, OCR installation or user-approval checkpoint merely because a Skill template suggests one.

Reuse completed review for unchanged reviewed content. If the change affects reviewed behavior, obtain the required review for that change; any stricter repository review-dismissal rules still apply. Resolve findings that violate the task's acceptance or existing contracts before delivery.

## Task planning material

Task notes and initiative indexes may describe dependencies, shared-file ownership and intended implementation order. Use those documents to understand the design and coordination context of the assigned task.

Metadata such as `status`, `depends_on`, `completion_pr` and `merge_sha`, when present, records the task note's planning or historical state. It is not necessary to synchronize every workflow transition back into Markdown.

## Completion

A repository delivery is complete after the task's required implementation and focused verification have passed review, the required repository checks pass, and the delivery PR merges.

If the task uncovers additional product or architecture work, track that work through the appropriate Issue or architecture process rather than folding it into completion bookkeeping.

Existing historical task records and reconciliation PRs remain useful audit history and do not need to be rewritten.
