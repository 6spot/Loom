---
task: M3-T3
issue: 50
status: completed
depends_on: [49]
created_at: 2026-08-21
started_at: 2026-08-21
completed_at: 2026-08-21
completion_pr: 56
merge_sha: abbd8faa26f671f58bc69dff832469e92ebc3dbf
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

- PR: #56
- merge SHA: `abbd8faa26f671f58bc69dff832469e92ebc3dbf`
- historical CI runs: `32495546544` (PR checks) and `32495589422` (post-merge main CI), all reported green; neither run invoked the explicit PostgreSQL 18 restart/resume step.
- restart/resume evidence: required run `32497391524` passed the explicit `PostgreSQL Runtime restart/resume vertical slice` step; archive revalidation run `32498967338` is also green.
- notes: `postgres_18_runtime_reconstruction_continues_world_and_pending_work` creates the World through `WorldService`, commits bootstrap state and immediate Work through `ActionService`, drops the first Runtime, reconnects the same isolated `TestDatabase`, reads Event/State/Work through the second Runtime/Storage ports, continues via a second Action, and executes inherited Work through normal claim/fence completion. PR #56 and its merge remain the historical implementation facts; the explicit restart/resume CI invocation was added and verified by the later PR #57 run and archive revalidation.

## Progress log

- 2026-08-21 — Task record created; waits on PostgreSQL lifecycle persistence #49.
- 2026-08-21 — Added the minimal PostgreSQL restart/resume vertical candidate in `crates/loom-storage/tests/postgres_restart_resume.rs`; no fixture rows, alternate write path, or persistent World lifecycle status are used.
- 2026-08-21 — PR #56 merged as `abbd8faa26f671f58bc69dff832469e92ebc3dbf`; the post-merge audit records the real merge and CI evidence.
- 2026-08-22 — Recorded the real explicit PostgreSQL 18 restart/resume evidence from required run `32497391524` and archive revalidation `32498967338`; the original PR #56 runs remain historical and did not invoke that explicit step.
