# Loom task notes

`docs/tasks/` preserves repository-local planning, scope, ownership and implementation evidence next to the code it describes.

GitHub Issues remain the collaboration surface for active tasks. Task notes complement them with durable context that is useful to future implementation and review.

The repository delivery procedure is [`../development/task-completion.md`](../development/task-completion.md).

## What belongs here

Task notes are useful when work benefits from repository-local context such as:

- bounded scope and file ownership;
- architecture or contract references;
- dependency/design diagrams;
- acceptance examples;
- verification evidence;
- historical implementation decisions.

A task note is optional unless the task or initiative explicitly uses one.

## Task metadata

Existing task records may contain metadata such as:

```yaml
---
task: C2-R1-T04
issue: 554
kind: leaf
status: in_progress
depends_on: [C2-R1-T01]
started_at: 2026-09-09
completed_at:
completion_pr:
merge_sha:
---
```

These fields summarize planning or historical information at the time the note was updated:

- `status` records the task note's current snapshot;
- `depends_on` documents intended sequencing;
- `completion_pr` and `merge_sha` may preserve delivery evidence;
- dates may record useful planning or completion history.

New task notes should include only metadata that materially helps the task.

## Dependency diagrams and initiative indexes

Initiative and milestone READMEs may describe dependency graphs, shared-file ordering and the intended delivery sequence. These documents are especially useful for understanding cross-task interfaces and avoiding conflicting edits.

When a task is assigned, use the graph and linked notes to understand its prerequisites and file boundaries, then execute the assigned scope against the current repository state.

## Completion and evidence

Useful task evidence can be recorded in the delivery PR and, when the task note is already being changed, in the same task note.

A separate post-merge documentation change is not part of the standard completion sequence. Final PR numbers, merge SHAs or later historical notes can still be added when they provide lasting value.

Historical reconciliation records remain valid implementation history.

## Architecture authority

Task notes never replace architecture authority.

Before architecture-sensitive implementation:

1. read `docs/architecture/README.md`;
2. resolve the current canonical source and reverse supersession entries;
3. read every relevant accepted Amendment;
4. use the Amendment process if the task requires a new semantic or authority decision.

A task note may reference an architecture decision; it may not create one by itself.

## Current initiative indexes

Current and historical task material remains organized under this directory, including:

- [`chronicle/README.md`](chronicle/README.md) and its delivery-round indexes;
- [`scheduler-discovery/README.md`](scheduler-discovery/README.md);
- [`validator/README.md`](validator/README.md);
- [`validator-recert/README.md`](validator-recert/README.md);
- [`v0-roadmap.md`](v0-roadmap.md).

These records preserve implementation planning and history alongside the repository.
