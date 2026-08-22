---
task: M12-T3
issue: 123
status: planned
depends_on: [92, 121, 122]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M12-T3 — Agent-Local Context Boundary

## Goal
Build bounded Agent context from explicitly visible information instead of exposing authoritative World view.

## Required implementation
- Runtime context builder selects permitted local facets/observations/relationships/semantic retrieval under explicit visibility policy.
- Default is not “all World data visible”.
- Semantic retrieval uses M8 boundary and budgets/ReadSet evidence.
- Context is pinned to one TimelineVersion/session and enforces entity/relationship/event/semantic/byte/depth budgets.
- Tests include hidden authoritative data that must remain inaccessible.

## Forbidden shortcuts
No BaseWorldView/storage to executor, whole-World serialization, hidden-State semantic fallback or mixed-version reads.

## Acceptance checklist
- [ ] allowed local evidence is visible;
- [ ] hidden authoritative data is inaccessible;
- [ ] semantic retrieval respects visibility/budgets;
- [ ] context ReadSet/provenance is captured;
- [ ] pinned-version concurrency tests pass;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after Agency SPI and semantic retrieval.
