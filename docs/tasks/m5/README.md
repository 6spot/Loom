# M5 — Timeline Logical Runtime + Deterministic Scheduler

Parent issue: #137. Depends on M4 gate #152.

## Dependency graph

```text
#153 Work logical target/due/order
  ↓
#154 Timeline Logical Journal
  ├── #155 FailurePolicy / blocked observability
  │      ↓
  │    #156 logical-head admission / claim
  │      ↓
  └──── #157 Chronology Budget + World-Time driver
          ├── #158 Reaction atomic scheduling
          └── #160 scheduler worker/topology
#150 ──> #159 Runtime entropy
all ──> #161 final gate
```

## Tasks

| Task | Issue | Status |
| --- | ---: | --- |
| M5-T1 | #153 | planned |
| M5-T2 | #154 | planned |
| M5-T3 | #155 | planned |
| M5-T4 | #156 | planned |
| M5-T5 | #157 | planned |
| M5-T6 | #158 | planned |
| M5-T7 | #159 | planned |
| M5-T8 | #160 | in_review |
| M5-T9 | #161 | planned |

The gate must prove same-Timeline `(effective_due_world_time, logical_schedule_order)` ordering, bounded liveness, head-aware claim, restart/fencing, chronology budget and explicit World-Time advancement.
