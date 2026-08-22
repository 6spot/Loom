# Milestone 5 Task Index — Timeline Ancestry + Fork

Parent issue: #67

Depends on M4 replay gate #66.

## Dependency graph

```text
#68 M5-T1 ancestry/fork/EventRef contract [SERIAL ROOT]
 ↓
#69 M5-T2 public fork API + InMemory head fork
 ↓
#70 M5-T3 PostgreSQL atomic head fork
 ↓
#71 M5-T4 historical fork
 ↓
#72 M5-T5 ancestry-aware history/causality
 ↓
#73 M5-T6 branch-isolation/restart gate [SERIAL GATE]
```

## Status

| Task | Issue | Status | Record |
| --- | ---: | --- | --- |
| M5-T1 ancestry/fork/EventRef contract | #68 | planned | `t1-timeline-ancestry-fork-contract.md` |
| M5-T2 API + InMemory head fork | #69 | planned | `t2-api-inmemory-head-fork.md` |
| M5-T3 PostgreSQL head fork | #70 | planned | `t3-postgres-head-fork.md` |
| M5-T4 historical fork | #71 | planned | `t4-historical-fork.md` |
| M5-T5 ancestry-aware history/causality | #72 | planned | `t5-ancestry-aware-history-causality.md` |
| M5-T6 branch isolation gate | #73 | planned | `t6-branch-isolation-gate.md` |

Parent #67 closes only after all rows are completed and #73 proves current/historical/multi-generation fork, causal visibility and branch-local State/Future across PostgreSQL restart.
