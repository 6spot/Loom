---
task: M12-T7
issue: 127
status: planned
depends_on: [121, 122, 123, 124, 125, 126]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M12-T7 — Agency / Cognition / Provenance Gate

## Goal
Prove cognition is visibility-limited, restartable, auditable and unable to bypass semantic authority.

## Required verification
With deterministic fake executor and neutral examples: create visible+hidden World data; prove hidden data cannot enter context; test NoAction no mutation; Act normal Action commit; schedule wake then kill/restart/resume; fork pending wake and verify new WorkId/branch isolation; inspect revision/executor/context/action/Event provenance after restart.

## Acceptance checklist
- [ ] hidden World data remains inaccessible;
- [ ] NoAction/Act semantics pass;
- [ ] Action authority/world binding is preserved;
- [ ] wake restart/fork/fencing passes on PostgreSQL;
- [ ] cognition provenance is complete;
- [ ] final architecture/fmt/check/clippy/tests/rustdoc/PostgreSQL/server candidate is green.

## Completion evidence
- PR:
- merge SHA:
- final candidate / CI:

## Progress log
- 2026-08-22 — Planned as M12 SERIAL GATE; real vendor LLM provider is not required.
