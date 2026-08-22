---
task: M10-T2
issue: 106
status: planned
depends_on: [105]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M10-T2 — Persist and Enforce World Capability Set

## Goal
Persist exact enabled Capabilities per World and enforce them at semantic execution/discovery boundaries.

## Required implementation
- Runtime-owned World Capability Set ports + PostgreSQL/InMemory binding state.
- Reject Actions owned by globally installed but disabled Capability.
- Enforce Work, Reaction and semantic-index ownership against World binding.
- Expose World-filtered Catalog separately from explicit global installed catalog.
- Forked Timelines inherit World binding; no branch silently changes software assembly.

## Forbidden shortcuts
No registry-only nondurable check, registry presence as enablement, concrete Capability object in World DB or per-Timeline software set without architecture change.

## Acceptance checklist
- [ ] bindings persist/reload;
- [ ] disabled Action/Work/Reaction/index cannot execute;
- [ ] World/global Catalog distinction passes;
- [ ] fork/restart preserves binding;
- [ ] InMemory/PostgreSQL parity passes;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after #105.
