# Automatic Scheduler Discovery Task Ledger

This initiative ledger is the durable execution map for automatic bounded
Timeline discovery in the official Loom server. Architecture authority remains
with [Amendment 0005](../../architecture/amendments/0005-automatic-bounded-timeline-discovery.md)
and the [Architecture Index](../../architecture/README.md); this directory
records task scope, dependency eligibility and verification evidence only.

## Execution model

The GitHub hierarchy has three levels:

- Root `#398` (`SCHD-R0`) is coordination-only and is never assigned to an
  executor.
- Stage trackers `#399`–`#402` (`SCHD-S1`–`SCHD-S4`) are coordination-only and
  are not executable task records.
- Leaves `#403`–`#423` (`SCHD-T01`–`SCHD-T21`) are the only executable units;
  each leaf has exactly one Markdown record in this directory.

Parent/child links express ownership. The `depends_on` values below are the
hard dependency graph and are the only inputs to READY eligibility. Closing a
stage tracker is not a hard dependency and must never be added to a leaf's
`depends_on` list.

## Task records

| Task | GitHub issue | Status | Depends on | Record |
| --- | ---: | --- | --- | --- |
| SCHD-T01 | #403 | in_progress | — | [t01-architecture-amendment.md](t01-architecture-amendment.md) |
| SCHD-T02 | #404 | planned | #403 | [t02-task-ledger-graph.md](t02-task-ledger-graph.md) |
| SCHD-T03 | #405 | planned | #404 | [t03-discovery-port.md](t03-discovery-port.md) |
| SCHD-T04 | #406 | planned | #405 | [t04-runtime-discovery.md](t04-runtime-discovery.md) |
| SCHD-T05 | #407 | planned | #405 | [t05-inmemory-discovery.md](t05-inmemory-discovery.md) |
| SCHD-T06 | #408 | planned | #405 | [t06-postgres-discovery-sql.md](t06-postgres-discovery-sql.md) |
| SCHD-T07 | #409 | planned | #405, #408 | [t07-pgstorage-discovery.md](t07-pgstorage-discovery.md) |
| SCHD-T08 | #410 | planned | #406, #407, #409 | [t08-discovery-parity-gate.md](t08-discovery-parity-gate.md) |
| SCHD-T09 | #411 | planned | #410 | [t09-supervisor-type.md](t09-supervisor-type.md) |
| SCHD-T10 | #412 | planned | #411 | [t10-supervisor-cycle.md](t10-supervisor-cycle.md) |
| SCHD-T11 | #413 | planned | #412 | [t11-supervisor-fairness.md](t11-supervisor-fairness.md) |
| SCHD-T12 | #414 | planned | #413 | [t12-supervisor-loop.md](t12-supervisor-loop.md) |
| SCHD-T13 | #415 | planned | #414 | [t13-server-supervisor-wiring.md](t13-server-supervisor-wiring.md) |
| SCHD-T14 | #416 | planned | #415 | [t14-remove-fixed-worker.md](t14-remove-fixed-worker.md) |
| SCHD-T15 | #417 | planned | #416 | [t15-remove-target-config.md](t15-remove-target-config.md) |
| SCHD-T16 | #418 | planned | #417 | [t16-compose-env-cleanup.md](t16-compose-env-cleanup.md) |
| SCHD-T17 | #419 | planned | #418 | [t17-docs-automatic-scheduler.md](t17-docs-automatic-scheduler.md) |
| SCHD-T18 | #420 | planned | #417 | [t18-new-world-auto-schedule.md](t18-new-world-auto-schedule.md) |
| SCHD-T19 | #421 | planned | #417 | [t19-fork-auto-schedule.md](t19-fork-auto-schedule.md) |
| SCHD-T20 | #422 | planned | #417 | [t20-restart-auto-resume.md](t20-restart-auto-resume.md) |
| SCHD-T21 | #423 | planned | #418, #419, #420, #421, #422 | [t21-final-compose-gate.md](t21-final-compose-gate.md) |

## Dependency graph

The graph below is copied from initiative root `#398`; stage tracker closure is
intentionally absent from every edge:

```text
S1 / #399
  #403 T01 -> #404 T02

S2 / #400
  #404 -> #405 T03
             |-> #406 T04 -----------\
             |-> #407 T05 ------------+-> #410 T08 [S2 GATE]
             \-> #408 T06 -> #409 T07 /

S3 / #401
  #410 T08 -> #411 T09 -> #412 T10 -> #413 T11 -> #414 T12 -> #415 T13 -> #416 T14 -> #417 T15

S4 / #402
  #417 -> #418 T16 -> #419 T17 -----------\
       -> #420 T18 ------------------------|
       -> #421 T19 ------------------------+-> #423 T21 [FINAL GATE]
       -> #422 T20 ------------------------/
```

`#423` also depends explicitly on `#418`, in addition to `#419`–`#422`.

## Cross-stage triggers

Cross-stage eligibility is driven by explicit leaf edges:

1. Completion of `#404` exposes `#405`, the first implementation leaf after
   the architecture/ledger stage. No `#399` closure edge is required.
2. Completion of the Stage-2 gate `#410` exposes `#411`. No `#400` closure
   edge is required.
3. Completion of `#417` exposes Stage-4 leaves `#418`, `#420`, `#421` and
   `#422` in parallel where their write scopes permit. No `#401` or `#402`
   closure edge is required.
4. Completion of `#418` exposes `#419`; completion of all five explicit
   prerequisites `#418`–`#422` exposes final gate `#423`.

The dispatcher must recompute READY leaves from task-file metadata after each
leaf's review/CI/evidence transition. A stage tracker may be reconciled for
coordination, but its GitHub OPEN/CLOSED state cannot block a leaf whose
declared leaf dependencies are completed.

## Record contract

Every leaf record uses the repository Task Ledger front matter:

```yaml
---
task: SCHD-Txx
issue: 000
status: planned # planned | in_progress | blocked | completed | cancelled
depends_on: []
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---
```

Completion requires the repository-level acceptance, review, CI and merge
evidence rules. Planned downstream records must not be marked `in_progress` or
`completed` before every declared hard dependency is completed. The first
mechanically selectable implementation leaf after T02 is therefore `SCHD-T03`
(`#405`) once `#403` and `#404` are both completed in the durable ledger.

## Scope boundary

All implementation leaves preserve the Amendment 0005 boundary: discovery is
bounded operational observation, while Runtime retains logical-head selection,
Work claimability, World-Time advancement and semantic commit authority. No
task in this ledger authorizes a replacement public API, message bus,
discovery reservation, bootstrap World or new Scheduler configuration variable.
