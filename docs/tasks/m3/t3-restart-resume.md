---
task: M3-T3
issue: 50
status: planned
depends_on: [49]
created_at: 2026-08-21
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M3-T3 — PostgreSQL Restart / Reload / Resume Vertical Slice

## Goal

Prove a World continues from PostgreSQL authority after Runtime compute stops and a new Runtime instance is assembled against the same database.

## Acceptance checklist

- [ ] create World through public `WorldService` on `PgStorage`;
- [ ] first Runtime commits initial state through a normal semantic Action;
- [ ] first Runtime persists pending Durable Work through the normal commit path;
- [ ] a second Runtime instance is assembled without fixture reseeding;
- [ ] second Runtime reads prior Event/State/Work from PostgreSQL authority;
- [ ] second semantic Action resolves from the first Runtime's durable state;
- [ ] inherited pending Work is claimable/executable with unchanged lease/fence semantics;
- [ ] no fake persistent paused/running World status is introduced.

## Completion evidence

- PR:
- merge SHA:
- CI runs:
- notes:

## Progress log

- 2026-08-21 — Task record created; waits on PostgreSQL lifecycle persistence #49.
