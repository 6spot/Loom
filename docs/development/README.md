# Loom development guides

This directory contains the current operational procedures for developing and testing Loom.

Use this index for the task categories defined in [`../../AGENTS.md`](../../AGENTS.md). Select the guide for the operation below and read its applicable sections; do not open every guide or follow every link. Documentation-only and read-only tasks do not acquire build, database or deployment requirements merely by opening this index.

## Current guides

| Operation or question | Guide |
| --- | --- |
| Start a clean checkout and exercise the public API | [`../quickstart.md`](../quickstart.md) — supported `loom-server` / `loom-client` / `loom-cli` workflow. |
| Understand or diagnose engine operation and public runtime behavior | [`../operator-guide.md`](../operator-guide.md) — time, work, provenance, replay, scheduler and Agent behavior. |
| Change core contracts or Cargo dependency edges | [`../developer-guide.md`](../developer-guide.md) — architecture lookup, Amendment gate and dependency governance. |
| Assess measured capacity or a performance claim | [`../capacity-envelope.md`](../capacity-envelope.md) — measured V0 capacity and unproven/deferred limits. |
| Deliver an authorized repository change | [`task-completion.md`](task-completion.md) — verification, review, required checks and PR merge. |
| Run PostgreSQL-backed tests | [`postgres-tests.md`](postgres-tests.md) — PostgreSQL 18 + pgvector environment and commands. |
| Change or verify runtime worker/executor behavior | [`runtime-worker.md`](runtime-worker.md) — topology and deterministic stress/restart checks. |

Deployment and production runbooks are intentionally separate under [`../deployment/README.md`](../deployment/README.md). Do not add a second deployment procedure here.

Upper-layer product development guidance is under [`../application-development/README.md`](../application-development/README.md). Repository Agent instructions remain in root `AGENTS.md`.

## Cargo build artifacts

- Cargo commands must use the workspace-local default `./target`.
- Do not set `CARGO_TARGET_DIR` unless a canonical development procedure explicitly requires it.
- Do not place Cargo build artifacts under `/tmp`, `/run`, `/run/user/*`, `$XDG_RUNTIME_DIR`, `~/.cache`, or any path outside the current workspace.
- This applies to development, testing, review, validation, and isolated verification runs.

## Scope

Development guides describe how to build, test and inspect the current implementation. They must conform to the architecture authority under `docs/architecture/` but must not duplicate architecture rules, application-development guidance, deployment runbooks or task history.

Keep one current guide per workflow. If a workflow changes, update its canonical guide and remove obsolete alternatives rather than keeping multiple sets of commands.
