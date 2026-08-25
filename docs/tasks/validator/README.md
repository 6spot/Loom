# Validator Task Ledger

This cross-cutting initiative verifies Loom through the same public consumer
surfaces available to supported applications. Validator scenarios must not
depend on Runtime, Storage, SQLx/PostgreSQL, or other implementation-only
authority.

## Tasks

| Task | Issue | Status | Depends on | Record |
| --- | ---: | --- | --- | --- |
| VAL-T1 | #253 | in_progress | — | [t1-validator-skeleton.md](t1-validator-skeleton.md) |
| VAL-T2 | #254 | in_progress | VAL-T1 | [t2-scenario-contract.md](t2-scenario-contract.md) |
| VAL-T3 | #255 | in_progress | VAL-T2 | [t3-runner-cli.md](t3-runner-cli.md) |
| VAL-T4 | #256 | in_progress | #254 | [t4-backend-harness.md](t4-backend-harness.md) |
| VAL-T5 | #257 | in_progress | #255, #256 | [t5-reports-evidence.md](t5-reports-evidence.md) |
| VAL-T6 | #258 | in_progress | #257 | [t6-task-ledger-feedback.md](t6-task-ledger-feedback.md) |
| VAL-T7 | #259 | in_progress | #258 | [t7-nonblocking-guardrails.md](t7-nonblocking-guardrails.md) |
| VAL-T8 | #260 | completed | #255, #256, #257, #259 | [t8-lifecycle-scenarios.md](t8-lifecycle-scenarios.md) |
| VAL-T9 | #261 | in_progress | #255, #256, #257, #259 | [t9-replay-fork-scenarios.md](t9-replay-fork-scenarios.md) |
| VAL-T10 | #262 | in_progress | VAL-T8, VAL-T9 | [t10-recursive-progression-gate.md](t10-recursive-progression-gate.md) |

The index is a navigation surface only. Each implementation task retains one
Markdown task record under this directory, and the repository-level Task Ledger
rules in [`../README.md`](../README.md) remain authoritative.
