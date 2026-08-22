# Milestone 4 Task Index — Deterministic Replay + Logical Commit Journal

Parent issue: #60

Baseline: Milestone 3 closed on `main` at `55766947cdb68bce218c917ebb949872ed796fd6`.

## Dependency graph

```text
#61 M4-T1  replay/logical-commit contract [SERIAL ROOT]
   ↓
#62 M4-T2  pure World replay engine
   ↓
#63 M4-T3  logical Work transition journal
   ↓
#64 M4-T4  PostgreSQL atomic logical journal
   ↓
#65 M4-T5  replay arbitrary TimelineVersion
   ↓
#66 M4-T6  replay parity gate [SERIAL GATE]
```

## Status

| Task | Issue | Status | Record |
| --- | ---: | --- | --- |
| M4-T1 replay/logical-commit contract | #61 | planned | `t1-replay-logical-commit-contract.md` |
| M4-T2 World replay engine | #62 | planned | `t2-world-replay-engine.md` |
| M4-T3 logical Work journal | #63 | planned | `t3-logical-work-transition-journal.md` |
| M4-T4 PostgreSQL logical journal | #64 | planned | `t4-postgres-logical-commit-journal.md` |
| M4-T5 historical-version replay | #65 | planned | `t5-replay-historical-version.md` |
| M4-T6 replay parity gate | #66 | planned | `t6-replay-parity-gate.md` |

## Milestone completion rule

Parent #60 closes only after every row is `completed`, every child issue is closed completed, and #66 records one final green candidate proving current/intermediate replay parity and logical Pending Work reconstruction on InMemory and PostgreSQL authority.
