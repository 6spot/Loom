---
task: SCHD-T02
issue: 404
status: completed
depends_on: [403]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at: 2026-08-30
completion_pr: 425
merge_sha: 3c6ef8699b8350587565e3271647327027d546dd
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

- [x] Every executable issue T01–T21 has exactly one task file.
- [x] Every task file has the same dependency relation as its GitHub issue.
- [x] Root/stage trackers are clearly non-executable.
- [x] The first READY implementation leaf after T02 is mechanically
      determinable as T03 (`#405`) after its declared prerequisites complete.
- [x] Real-ledger/task-graph governance checks include this initiative.
- [x] Documentation/governance CI passes.

## Progress Log

- 2026-08-30 — Added the scheduler-discovery initiative index, registered it
  from the repository task ledger, and created one record for each executable
  issue `#404`–`#423` with the root graph's exact dependencies.
- 2026-08-30 — Delivery PR #425 merged at
  `3c6ef8699b8350587565e3271647327027d546dd`; completion metadata was later
  reconciled after historical ledger drift was detected by T10 CI.
