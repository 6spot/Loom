# Loom task completion workflow

This guide describes the standard repository delivery path for executable Loom work.

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

- Run the focused tests, builds and static checks that exercise the modified behavior.
- Use the repository's real integration environment when the task requires database, service, browser or deployment behavior.
- Record checks that could not be run and why.
- A successful unrelated suite does not substitute for verification of the changed contract.

The current CI workflows remain the source for repository merge checks.

## Task planning material

Task notes and initiative indexes may describe dependencies, shared-file ownership and intended implementation order. Use those documents to understand the design and coordination context of the assigned task.

Metadata such as `status`, `depends_on`, `completion_pr` and `merge_sha`, when present, records the task note's planning or historical state. It is not necessary to synchronize every workflow transition back into Markdown.

## Completion

A repository delivery is complete after the task's required implementation and focused verification have passed review, the required repository checks pass, and the delivery PR merges.

If the task uncovers additional product or architecture work, track that work through the appropriate Issue or architecture process rather than folding it into completion bookkeeping.

Existing historical task records and reconciliation PRs remain useful audit history and do not need to be rewritten.
