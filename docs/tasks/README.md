# Loom task notes

`docs/tasks/` preserves durable planning, scope, ownership and implementation evidence next to the code it describes.

It is not Loom's workflow engine.

GitHub Issues remain the collaboration surface. When an external orchestrator such as Multica coordinates execution, that orchestrator owns task state, dependency readiness, parent/child relationships and Stage scheduling. GitHub PRs and required checks own repository delivery/merge facts.

The repository completion procedure is [`../development/task-completion.md`](../development/task-completion.md).

## What belongs here

Task notes are useful for work that benefits from durable repository-local context, for example:

- bounded scope and file ownership;
- architecture or contract references;
- dependency/design diagrams;
- acceptance examples;
- verification evidence;
- historical implementation decisions.

Do not create or update a task note merely because every executable Issue is expected to have a Markdown mirror.

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

These fields remain valid historical/contextual metadata, but they are not repository-wide workflow authority.

In particular:

- `status` does not override the active Issue/orchestrator state;
- `depends_on` documents intended sequencing but does not independently decide READY eligibility;
- `completion_pr` and `merge_sha` are optional evidence, not mandatory post-merge reconciliation fields;
- stale metadata must not block work that the active orchestrator has made ready.

New task notes should include only metadata that materially helps the task. Do not add fields merely to duplicate state already owned by GitHub or Multica.

## Dependency diagrams and initiative indexes

Initiative and milestone READMEs may describe dependency graphs and shared-file ordering. Treat those graphs as design/coordination context.

Runtime scheduling comes from the active orchestrator. When Multica is used, its Issue dependency and Stage graph is authoritative for deciding which task runs next.

Legacy initiative text that says READY must be derived from `status: completed` on the default branch is superseded by this repository-wide rule.

File ownership, architecture boundaries and explicit sequencing constraints remain real constraints even when task-state metadata is non-authoritative.

## Completion and evidence

A repository delivery is complete when the implementation has the required focused verification/review/CI and its delivery PR merges, subject to any task-specific product acceptance that is actually part of the Issue.

Do not require a second PR solely to write:

```yaml
status: completed
completion_pr: ...
merge_sha: ...
```

after the delivery has already merged.

If a task note is part of the delivery, update useful acceptance/evidence in that same PR when practical. Historical reconciliation records do not need to be removed or rewritten.

## Architecture authority

Task notes never replace architecture authority.

Before architecture-sensitive implementation:

1. read `docs/architecture/README.md`;
2. resolve the current canonical source and reverse supersession entries;
3. read every relevant accepted Amendment;
4. stop and use the Amendment process if the task requires a new semantic or authority decision.

A task note may reference an architecture decision; it may not create one by itself.

## Current initiative indexes

Current and historical task material remains organized under this directory, including:

- [`chronicle/README.md`](chronicle/README.md) and its delivery-round indexes;
- [`scheduler-discovery/README.md`](scheduler-discovery/README.md);
- [`validator/README.md`](validator/README.md);
- [`validator-recert/README.md`](validator-recert/README.md);
- [`v0-roadmap.md`](v0-roadmap.md).

These records preserve useful implementation history. Their status tables are documentary snapshots unless the active Issue explicitly makes a specific record part of product acceptance.
