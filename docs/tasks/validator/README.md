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

The index is a navigation surface only. Each implementation task retains one
Markdown task record under this directory, and the repository-level Task Ledger
rules in [`../README.md`](../README.md) remain authoritative.
