---
task: SCHD-T02
issue: 404
status: planned
depends_on: [403]
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T02 — Register scheduler-discovery Task Ledger + executable dependency graph

## Goal

Create the durable repository task graph for automatic bounded Scheduler
Timeline discovery after Architecture Amendment 0005 is accepted, so the
dispatcher can select READY leaves without another planning turn.

## Scope

- Add the initiative index and register it from `docs/tasks/README.md`.
- Add exactly one planned task record for each executable GitHub issue
  `#404`–`#423`; retain the existing `#403` record as T01's record.
- Copy the exact issue numbers and hard dependency edges from initiative root
  `#398`.
- Document Root/stage/leaf execution rules and the cross-stage triggers.
- Register the scheduler ledger with the existing `validator_ready.py`
  governance check; do not create a second task-graph implementation.

## Boundaries

Root `#398` and stage trackers `#399`–`#402` remain non-executable. The
`depends_on` graph is leaf-only: stage closure is coordination and must not be
used as a hard dependency. This task does not change Runtime/Storage/Server
implementation, dependency semantics or any downstream task status.

## Acceptance

- [ ] Every executable issue T01–T21 has exactly one task file.
- [ ] Every task file has the same dependency relation as its GitHub issue.
- [ ] Root/stage trackers are clearly non-executable.
- [ ] The first READY implementation leaf after T02 is mechanically
      determinable as T03 (`#405`) after its declared prerequisites complete.
- [ ] Real-ledger/task-graph governance checks include this initiative.
- [ ] Documentation/governance CI passes.

## Progress Log

- 2026-08-30 — Added the scheduler-discovery initiative index, registered it
  from the repository task ledger, and created one record for each executable
  issue `#404`–`#423` with the root graph's exact dependencies. The record is
  kept `planned` until its declared prerequisite `#403` is completed in the
  canonical ledger.
