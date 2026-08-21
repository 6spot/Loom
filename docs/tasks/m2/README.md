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
| M2-T3 PostgreSQL commit/CAS | #28 | completed | `t3-postgresql-commit-cas.md` |
| M2-T4 PostgreSQL Work leases | #29 | completed | `t4-postgresql-work-leases.md` |
| M2-T5 PostgreSQL test/CI infrastructure | #30 | completed | `t5-postgresql-test-infra.md` |
| M2-T6 PostgreSQL final parity gate | #31 | completed | `t6-postgresql-final-gate.md` |

## Milestone completion rule

The parent issue #25 may close only when every row above is `completed`, every child issue is closed as completed, and the final gate records one final `main` candidate SHA with green architecture, formatting, build, clippy, workspace tests, rustdoc, migrations and PostgreSQL parity/concurrency tests.

## Scope guard

This milestone covers PostgreSQL 18 + SQLx authoritative persistence for the Runtime persistence contracts. It does not add pgvector semantic retrieval, object storage, transport, provider/LLM integration, domain-rich Capabilities or distributed transactions.

## Administrative notes

- 2026-08-21: #32 was accidentally created as a duplicate of M2-T5 #30 and immediately closed with reason `duplicate`. #30 remains the only authoritative T5 issue/task.
- 2026-08-21: M2-T1 #26 completed via PR #34, merged as `8823b3d9d2f4963bce4a04c31343aeeca7b02ac1`; final implementation CI run `32445927597` passed the Rust matrix and PostgreSQL 18 schema contract.
- 2026-08-21: M2-T2 #27 completed via PR #36, merged as `7a8e2c424466268867f68e611a7bafcc0e988f4e`; implementation CI run `32452222573` and final task-record CI run `32452416780` passed PostgreSQL 18 persistence parity plus Ubuntu/macOS Architecture, Format, Check, Clippy, Test and Rustdoc.
- 2026-08-21: M2-T3 #28 completed via PR #38, merged as `9480211108790cb41eabf46da7b29577100205c0`; final task-record CI run `32456912832` passed PostgreSQL 18 commit/CAS/concurrency/atomicity parity plus Ubuntu/macOS Architecture, Format, Check, Clippy, Test and Rustdoc.
- 2026-08-21: M2-T4 #29 completed via PR #40, merged as `7236dbcf37288ae8a8d892242a27bf784b583cab`; clean implementation CI run `32460351746` and final task-record CI run `32460630084` passed PostgreSQL 18 Work lease/fence/concurrency parity plus Ubuntu/macOS Architecture, Format, Check, Clippy, Test and Rustdoc.
- 2026-08-21: M2-T5 #30 completed via PR #42, merged as `9f2051d3098b1b321508bff115390541646f1a41`; clean implementation CI run `32463175121` and final task-record CI run `32463486023` passed isolated PostgreSQL 18 schema/migration, read, commit/CAS, Durable Work and stale-fence suites plus Ubuntu/macOS Architecture, Format, Check, Clippy, Test and Rustdoc.
- 2026-08-21: M2-T6 #31 final code candidate `af7c1de52a2733e20a8b9285dbc4b0da90e7c188` on PR #44 passed clean candidate CI `32464761591` and final task-record CI `32465745436`, including PostgreSQL 18 public Runtime/API vertical parity plus the complete schema/migration, read, commit/CAS/atomicity, Durable Work and stale-fence suites and Ubuntu/macOS Architecture, Format, Check, Clippy, Test and Rustdoc. PR #44 merged as `96622329aa36e37b66ecd63f719fd0e87fa4dd29`; post-merge audit CI must pass before #31 and parent #25 close.
