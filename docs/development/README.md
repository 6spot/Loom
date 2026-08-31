# Loom development guides

This directory contains the current operational procedures for developing and testing Loom.

## Current guides

- [`../quickstart.md`](../quickstart.md) — V0 public quickstart from a clean checkout using only `loom-server` / `loom-client` / `loom-cli` (no Runtime/Storage imports, no direct DB).
- [`../operator-guide.md`](../operator-guide.md) — V0 operator reference: Installed vs Binding vs Assembly, World Time vs Platform Time, logical Work vs lease, head/quiescence/budget, missing implementation/terminalization, Revision/Session provenance, replay vs rerun, fork ancestry, Agent visibility/CAS resample.
- [`../developer-guide.md`](../developer-guide.md) — V0 developer reference: Architecture Index supersession lookup, Amendment gate, task-ledger workflow, Cargo DAG and verification.
- [`../capacity-envelope.md`](../capacity-envelope.md) — measured V0 capacity envelope from M11 (`loom-bench`); larger-scale claims marked unproven/deferred.
- [`task-completion.md`](task-completion.md) — canonical executable-task completion workflow: review/CI, delivery merge, post-merge Task Ledger reconciliation on the default branch, ledger governance, GitHub Issue closure and final external status.
- [`postgres-tests.md`](postgres-tests.md) — local PostgreSQL 18 + pgvector integration-test service, environment and test commands.
- [`runtime-worker.md`](runtime-worker.md) — v0 worker/executor topology and deterministic stress/restart evidence.

Deployment and production runbooks are intentionally separate under [`../deployment/README.md`](../deployment/README.md). Do not add a second deployment procedure here.

Agent-specific repository workflow is under [`../agents/README.md`](../agents/README.md).

## Cargo build artifacts

- Cargo commands must use the workspace-local default `./target`.
- Do not set `CARGO_TARGET_DIR` unless a canonical development procedure explicitly requires it.
- Do not place Cargo build artifacts under `/tmp`, `/run`, `/run/user/*`, `$XDG_RUNTIME_DIR`, `~/.cache`, or any path outside the current workspace.
- This applies to development, testing, review, validation, and isolated verification runs.

## Scope

Development guides describe how to build, test and inspect the current implementation. They must conform to the architecture authority under `docs/architecture/` but must not duplicate architecture rules, deployment runbooks or task history.

Keep one current guide per workflow. If a workflow changes, update its canonical guide and remove obsolete alternatives rather than keeping multiple sets of commands.
