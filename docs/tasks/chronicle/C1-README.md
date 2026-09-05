# Chronicle C1 — Historical World

Root Issue: #489
Status: in_progress

C1 turns the completed C0 source-grounded vertical slice into a repeatable Book-to-Chronicle production system and then uses that system to build the first high-density late-Han / early-Three-Kingdoms Historical World experience.

The Root Issue is coordination-only. Only the executable C1-T1 through C1-T17 records below may be assigned to an implementation agent, and only when their `depends_on` tasks are `completed` in the canonical Task Ledger on the default branch.

## Task graph

| Task | Issue | Status | Depends on | Scope |
| --- | ---: | --- | --- | --- |
| C1-T1 | #490 | completed | C0-T12 | ingestion control-plane contract + persistence |
| C1-T2 | #491 | completed | C1-T1 | Rust Chronicle server + API namespaces + single-admin auth |
| C1-T3 | #492 | completed | C1-T2 | Document upload + immutable revisions/source storage |
| C1-T4 | #493 | completed | C1-T1, C1-T2 | durable PostgreSQL-backed ingestion worker/resume |
| C1-T5 | #494 | completed | C1-T3, C1-T4 | structure detection + semantic segmentation + context state |
| C1-T6 | #495 | completed | C1-T5 | context-aware contract-first chunk extraction |
| C1-T7 | #496 | completed | C1-T6 | source assembly + within-book resolution |
| C1-T8 | #497 | completed | C1-T7 | cross-source review + canonical publication |
| C1-T9 | #498 | completed | C1-T2 | React/Vite web foundation + shadcn Studio shell |
| C1-T10 | #499 | completed | C1-T3, C1-T4, C1-T9 | Studio document/import operations + progress |
| C1-T11 | #500 | completed | C1-T8, C1-T9 | Studio resolution review queue |
| C1-T12 | #501 | completed | C1-T8, C1-T9 | zh-CN Reader Presentation projection |
| C1-T13 | #502 | completed | C1-T10, C1-T11, C1-T12 | first high-density historical corpus pack |
| C1-T14 | #503 | planned | C1-T13 | corpus Coverage model/visibility |
| C1-T15 | #504 | planned | C1-T13, C1-T14 | Historical Moment projection/API |
| C1-T16 | #505 | planned | C1-T9, C1-T12, C1-T15 | World page + global historical time context |
| C1-T17 | #506 | planned | C1-T16 | final real Debian Book-to-Chronicle/Historical World gate |

## Execution spine

```text
C1-T1
  -> C1-T2
      -> C1-T3
      -> C1-T4
           -> C1-T5
                -> C1-T6
                     -> C1-T7
                          -> C1-T8

C1-T2 -> C1-T9
C1-T3 + C1-T4 + C1-T9 -> C1-T10
C1-T8 + C1-T9 -> C1-T11
C1-T8 + C1-T9 -> C1-T12
C1-T10 + C1-T11 + C1-T12 -> C1-T13
C1-T13 -> C1-T14
C1-T13 + C1-T14 -> C1-T15
C1-T9 + C1-T12 + C1-T15 -> C1-T16
C1-T16 -> C1-T17
```

Transitive dependencies mean C1-T17 is the serial final gate over the complete C1 graph.

## Frozen planning boundaries

- Chronicle remains application-owned product logic/persistence and must not redefine Loom Core/Runtime/Storage authority.
- Existing C0 staged / Resolution / canonical publication semantics are reused, not bypassed.
- Long-lived server/control-plane direction is Rust-first; existing Python model/ingestion work is retained while semantics are still being validated and may be migrated gradually later.
- Public + Studio use one React/TypeScript/Vite web application. Public styling remains Chronicle-specific; Studio uses shadcn/ui and is deliberately engineering-oriented.
- Studio uses one environment-configured administrator. C1 adds no User/Role/RBAC domain.
- PostgreSQL is the initial durable job queue; no Redis/Celery/RabbitMQ without measured need.
- Uploaded source revisions are immutable. Replacement creates a superseding revision rather than destructive overwrite.
- Persist one base Reader Presentation language (`zh-CN`); multilingual/world-history work is deferred.
- Semantic chunks are model-processing units, never historical identity/truth boundaries.
- Reader Presentation is derived and Claim/source traceable; it cannot become historical authority.

## READY / Multica rule

GitHub Issue state is collaboration state, not READY authority. Multica/agents must read this index plus the child task record and calculate readiness from the canonical default-branch Task Ledger. A delivery PR merge alone does not complete a task; `docs/development/task-completion.md` post-merge reconciliation remains mandatory.

After the C1-T13 reconciliation reaches the default branch, the current READY leaf is **C1-T14 / #503**. Its sole hard dependency C1-T13 is completed. **C1-T15 / #504 remains blocked** until C1-T14 is canonically completed; C1-T16 and C1-T17 remain transitively blocked behind it.

## Governance repair note

C1-T1/T2/T3/T5/T6/T7/T8/T9 delivery PRs were merged and their GitHub Issues were advanced/closed before the required default-branch Task Ledger reconciliation. The catch-up reconciliation does not retroactively make that sequencing compliant; it restores the canonical ledger to the factual delivered state using the actual delivery PR, merge SHA, and exact-head CI evidence. C1-T10 through C1-T13 follow the required sequence: exact-head checks -> delivery merge -> ledger reconciliation -> Issue closure.

## Final completion

C1 closes only after C1-T17 is canonically completed and #489 is reconciled. The final gate must prove the real Studio upload -> durable job -> segmentation/context -> extraction -> review/resolution -> canonical publication -> zh-CN Reader Presentation -> expanded corpus -> Historical Moment/World flow on the supported Debian/PostgreSQL 18 deployment, including restart/retry and source-revision supersession evidence.

If any child discovers a new Loom semantic/authority decision, stop that child and use the Architecture Amendment process.
