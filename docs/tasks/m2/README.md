# Milestone 2 Task Index — PostgreSQL 18 + SQLx Authoritative Persistence

Parent issue: #25

Baseline: Milestone 1 completed on `main`; persistence semantics are already proven against `InMemoryStore` and must not change merely because PostgreSQL becomes authoritative.

## Dependency graph

```text
#26 M2-T1  PostgreSQL schema + SQLx migrations
   ├── #27 M2-T2  WorldStore / snapshot read parity
   ├── #28 M2-T3  CommitStore / Timeline CAS / materialization
   ├── #29 M2-T4  Durable Work lease / claim / retry fencing
   └── #30 M2-T5  PostgreSQL integration-test / CI infrastructure
                    │
                    └────────────┐
#27 + #28 + #29 + #30 ───────────┴──> #31 M2-T6 final parity gate
```

## Status

| Task | Issue | Status | Record |
| --- | ---: | --- | --- |
| M2-T1 PostgreSQL schema + SQLx migrations | #26 | completed | `t1-postgresql-schema.md` |
| M2-T2 PostgreSQL read parity | #27 | completed | `t2-postgresql-read-parity.md` |
| M2-T3 PostgreSQL commit/CAS | #28 | planned | `t3-postgresql-commit-cas.md` |
| M2-T4 PostgreSQL Work leases | #29 | planned | `t4-postgresql-work-leases.md` |
| M2-T5 PostgreSQL test/CI infrastructure | #30 | planned | `t5-postgresql-test-infra.md` |
| M2-T6 PostgreSQL final parity gate | #31 | planned | `t6-postgresql-final-gate.md` |

## Milestone completion rule

The parent issue #25 may close only when every row above is `completed`, every child issue is closed as completed, and the final gate records one final `main` candidate SHA with green architecture, formatting, build, clippy, workspace tests, rustdoc, migrations and PostgreSQL parity/concurrency tests.

## Scope guard

This milestone covers PostgreSQL 18 + SQLx authoritative persistence for the Runtime persistence contracts. It does not add pgvector semantic retrieval, object storage, transport, provider/LLM integration, domain-rich Capabilities or distributed transactions.

## Administrative notes

- 2026-08-21: #32 was accidentally created as a duplicate of M2-T5 #30 and immediately closed with reason `duplicate`. #30 remains the only authoritative T5 issue/task.
- 2026-08-21: M2-T1 #26 completed via PR #34, merged as `8823b3d9d2f4963bce4a04c31343aeeca7b02ac1`; final implementation CI run `32445927597` passed the Rust matrix and PostgreSQL 18 schema contract.
- 2026-08-21: M2-T2 #27 completed via PR #36, merged as `7a8e2c424466268867f68e611a7bafcc0e988f4e`; implementation CI run `32452222573` and final task-record CI run `32452416780` passed PostgreSQL 18 persistence parity plus Ubuntu/macOS Architecture, Format, Check, Clippy, Test and Rustdoc.
