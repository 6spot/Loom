---
task: M11-T7
issue: 119
status: planned
depends_on: [113, 114, 115, 116, 117, 118]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M11-T7 — Runtime Upgrade / Provenance Gate

## Goal
Prove software evolution is auditable and cannot rewrite World history.

## Required verification
Activate R1; run Action/Work/Ingress sessions and capture provenance. Publish/activate R2 without World changes; prove new sessions pin R2 while any running R1 session remains R1. Query Event↔Session↔Revision after restart; invalid activation changes neither active revision nor World.

## Acceptance checklist
- [ ] old Events/sessions remain R1 and new sessions use R2;
- [ ] no session switches revision mid-flight;
- [ ] every committed Event has producing session link;
- [ ] rejected/no-change/failed sessions remain auditable;
- [ ] Admin returns evidence without secrets/authority leakage;
- [ ] restart and final architecture/fmt/check/clippy/tests/rustdoc/PostgreSQL/server candidate pass.

## Completion evidence
- PR:
- merge SHA:
- final candidate / CI:

## Progress log
- 2026-08-22 — Planned as M11 SERIAL GATE.
