---
task: M6-T2
issue: 76
status: planned
depends_on: [75]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M6-T2 — Full Capability Catalog

## Goal
Make `loom-api` the complete discovery surface for registered Loom semantics.

## Required implementation
Expose deterministic descriptors for Capability manifests/dependencies, Actions, Facets, Relationships/roles, Events/associations, Scopes, WorkHandlers, Reactions, schema revisions/descriptions/JSON Schemas. Runtime derives metadata from registry; executable resolver/handler objects never cross API.

## Forbidden shortcuts
No `CapabilityRegistry`/resolver/Runtime authority leakage, per-Capability public endpoints or concrete Capability dependency in `loom-api`.

## Acceptance checklist
- [ ] every semantic category has a descriptor;
- [ ] owner/schema/version/relevant role/dependency data is present;
- [ ] catalog ordering is deterministic;
- [ ] empty/multi-Capability catalogs pass tests;
- [ ] no executable SPI leaks;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned; parallel-safe only after #75.
