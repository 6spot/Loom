---
task: M4-T4
issue: 64
status: planned
depends_on: [61, 63]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M4-T4 — PostgreSQL Atomic Logical Commit Journal

## Goal

Persist logical Timeline commits and Work transitions in the same PostgreSQL authority transaction as Event/State/Work mutation.

## Required implementation

- Add additive SQLx migration(s) for logical Timeline commit and Work-transition records.
- Write required journal rows in the exact authority transaction for Event-only, Work-only, mixed and current-Work-completion commits.
- Preserve rollback both ways: no journal without authority commit and no successful authority commit missing required journal rows.
- Add deterministic indexed history reads for reconstruction.
- Keep claim/lease/fence/retry operations out of logical history.

## Forbidden shortcuts

- No post-commit best-effort inserts, hidden trigger-owned semantics or fake Events.
- Do not rewrite shipped migrations or introduce `loom-runtime -> loom-storage`.

## Acceptance checklist

- [ ] fresh PostgreSQL 18 migrations pass;
- [ ] all logical commit shapes write correct rows;
- [ ] forced failures roll back authority and journal together;
- [ ] claim/retry operations add no logical history;
- [ ] ordered history survives process reconstruction and matches InMemory semantics;
- [ ] architecture/fmt/check/clippy/tests/rustdoc + PostgreSQL integration pass.

## Completion evidence

- PR:
- merge SHA:
- verification:

## Progress log

- 2026-08-22 — Planned after #63.
