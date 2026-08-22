---
task: M10-T7
issue: 111
status: planned
depends_on: [105, 106, 107, 108, 109, 110]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M10-T7 — Template / Capability Isolation Gate

## Goal
Prove Template birth recipes and per-World Capability assemblies are atomic and immutable across Worlds/revisions.

## Required verification
Create Worlds A/B from distinct Templates and prove disabled globally-installed semantics cannot execute. Publish new Template A revision; existing A stays unchanged while new A2 receives the new exact recipe. Exercise bootstrap rollback, restart, replay and fork while preserving bindings.

## Acceptance checklist
- [ ] distinct Templates create distinct valid Worlds;
- [ ] Action/Work/Reaction/index enablement is enforced per World;
- [ ] Template revision never mutates existing World;
- [ ] new World receives new revision exactly;
- [ ] bootstrap rollback/restart/replay/fork parity pass;
- [ ] final architecture/fmt/check/clippy/tests/rustdoc/PostgreSQL candidate is green.

## Completion evidence
- PR:
- merge SHA:
- final candidate / CI:

## Progress log
- 2026-08-22 — Planned as M10 SERIAL GATE.
