---
task: M3-T3
issue: 50
status: in_progress
depends_on: [49]
created_at: 2026-08-21
started_at: 2026-08-21
completed_at:
completion_pr:
merge_sha:
---

# M3-T3 — PostgreSQL Restart / Reload / Resume Vertical Slice

## Goal

Prove a World continues from PostgreSQL authority after Runtime compute stops and a new Runtime instance is assembled against the same database.

## Acceptance checklist

- [x] create World through public `WorldService` on `PgStorage`;
- [x] first Runtime commits initial state through a normal semantic Action;
- [x] first Runtime persists pending Durable Work through the normal commit path;
- [x] a second Runtime instance is assembled without fixture reseeding;
- [x] second Runtime reads prior Event/State/Work from PostgreSQL authority;
- [x] second semantic Action resolves from the first Runtime's durable state;
- [x] inherited pending Work is claimable/executable with unchanged lease/fence semantics;
- [x] no fake persistent paused/running World status is introduced.

## Completion evidence

- PR:
- merge SHA:
- CI runs:
- notes: Candidate test `postgres_18_runtime_reconstruction_continues_world_and_pending_work` creates the World through `WorldService`, commits bootstrap state and immediate Work through `ActionService`, drops the first Runtime, reconnects the same isolated `TestDatabase`, reads Event/State/Work through the second Runtime/Storage ports, continues via a second Action, and executes inherited Work through normal claim/fence completion. Local targeted test passed against the available PostgreSQL 17 container; PostgreSQL 18 CI and merge evidence remain pending.

## Progress log

- 2026-08-21 — Task record created; waits on PostgreSQL lifecycle persistence #49.
- 2026-08-21 — Added the minimal PostgreSQL restart/resume vertical candidate in `crates/loom-storage/tests/postgres_restart_resume.rs`; no fixture rows, alternate write path, or persistent World lifecycle status are used.
