---
task: SCHD-T11
issue: 413
status: planned
depends_on: [412]
created_at: 2026-08-30
started_at:
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T11 — Add bounded round-robin cursor progression across Timeline pages

## Goal

Advance an in-process discovery frontier across bounded Supervisor cycles so
later stable Timelines cannot be permanently starved.

## Scope and acceptance

- [ ] Persist only an operational in-memory cursor and advance it from the T03
      continuation; wrap at the ordered scan end.
- [ ] Tolerate target creation/removal and reset safely when the cursor has no
      successor; treat the cursor as a hint, never persisted authority.
- [ ] Blocked/Idle/normal outcomes for an earlier target cannot starve later
      targets.
- [ ] Deterministic tests cover bounded repeated visits, wrap, blocked first
      target, deletion and later target addition.
- [ ] No reservation table, randomness, persistent cursor, weighted priority or
      per-target parallelism is introduced.
