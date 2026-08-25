# M4 — Architecture Reconciliation Foundation

Parent issue: #136

M4 migrates the already-completed M1–M3 implementation to the current architecture after Amendments 0001–0003. It is not a greenfield rewrite and not an architecture-design phase.

## Dependency graph

```text
#146 Event / World-Time authority
  ↓
#147 World Runtime Binding
  ├── #148 Template / atomic World birth
  └── #149 minimum Runtime Revision
           ↓
         #150 root Execution Session / Assembly
           ↓
         #151 neutral fixtures
           ↓
         #152 reconciliation gate
```

#152 also depends on every prior M4 task.

## Tasks

| Task | Issue | Status | Purpose |
| --- | ---: | --- | --- |
| M4-T1 | #146 | completed | Runtime-stamped Event time + explicit World-Time transition |
| M4-T2 | #147 | completed | Immutable per-World Runtime Binding + legacy migration |
| M4-T3 | #148 | completed | Template validation + atomic World birth |
| M4-T4 | #149 | completed | Minimum Runtime Revision ledger/active selection |
| M4-T5 | #150 | completed | Root Execution Session + exact Execution Assembly |
| M4-T6 | #151 | completed | Neutral Template/Binding fixtures |
| M4-T7 | #152 | completed | Revalidate M1–M3 under current authority chain |
| M4-I1 | #209 | completed | Centralized PostgreSQL SQL ownership prerequisite |

## Gate

No M5 implementation starts until #152 proves Event time, World Time, Binding, Template birth, Revision and Session pinning on the same PostgreSQL-backed baseline.
