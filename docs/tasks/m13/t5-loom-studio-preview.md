---
task: M13-T5
issue: 133
status: planned
depends_on: [101, 129]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M13-T5 — Optional `loom-studio` Native Preview

> **NON-BLOCKING ENGINE V0 PREVIEW.** This record may remain `planned`/open after Engine V0 closes. Never mark it completed without a real preview implementation and evidence.

## Goal
Optionally establish a minimal GPUI native Loom consumer once a concrete reproducible upstream revision is pinned.

## Required implementation if undertaken
- Validate and pin exact GPUI/Zed revision; never float `main`.
- Add `apps/loom-studio` consuming only formal HTTP Loom client/API.
- Minimal native UI: World create/list/inspect, Timeline, Catalog-driven Action form, History, fork and Change Feed; provenance optional.
- Isolate GPUI dependencies to application crate. Web/WASM is post-V0.

## Forbidden shortcuts
No GPUI in engine/framework crates, direct embedded Runtime bypass, unpinned git dependency or making this issue a dependency of #134.

## Acceptance checklist if implemented
- [ ] pinned build is reproducible;
- [ ] formal Loom client/API only;
- [ ] minimal workflow works;
- [ ] engine DAG remains unchanged;
- [ ] supported native architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned as explicitly non-blocking preview work.
