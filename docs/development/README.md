# Loom development guides

This directory contains the current operational procedures for developing and testing Loom.

## Current guides

- [`postgres-tests.md`](postgres-tests.md) — local PostgreSQL 18 + pgvector integration-test service, environment and test commands.

## Cargo build artifacts

- Cargo commands must use the workspace-local default `./target`.
- Do not set `CARGO_TARGET_DIR` unless a canonical development procedure explicitly requires it.
- Do not place Cargo build artifacts under `/tmp`, `/run`, `/run/user/*`, `$XDG_RUNTIME_DIR`, `~/.cache`, or any path outside the current workspace.
- This applies to development, testing, review, validation, and isolated verification runs.

## Scope

Development guides describe how to run, test and inspect the current implementation. They must conform to the architecture authority under `docs/architecture/` but must not duplicate architecture rules or task history.

Keep one current guide per workflow. If a workflow changes, update its guide and remove obsolete alternatives rather than keeping multiple sets of commands.
