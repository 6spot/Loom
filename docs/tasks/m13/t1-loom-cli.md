---
task: M13-T1
issue: 129
status: planned
depends_on: [101, 127]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M13-T1 — `apps/loom-cli` Over Formal Loom API Client

## Goal
Create the official CLI as a pure public API consumer for developer/operator and V0 black-box workflows.

## Required implementation
- Add workspace CLI depending on the formal HTTP Loom client/`loom-api` only as architecture permits.
- Commands cover Template/Catalog, World create/inspect, Action, Facet query, History, Entity/Relationship trajectory, causes/effects, fork, feed tail/resume, Ingress, Runtime revision/provenance.
- Support deterministic JSON output plus human-readable mode, stable IDs/cursors and meaningful error exit codes.
- Server URL/auth are config/env concerns; validate local syntax but server remains authority.
- Integration tests exercise server/mock client without direct Runtime/DB access.

## Forbidden shortcuts
No Runtime/Storage/Capability/PgStorage import, direct DB/Admin table access, Capability-specific required commands or shadow DTO protocol.

## Acceptance checklist
- [ ] CLI builds/documents core V0 commands;
- [ ] workflows use server/public client only;
- [ ] JSON output is scriptable/deterministic;
- [ ] errors/exit codes are meaningful;
- [ ] feed/fork/provenance commands pass;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned as M13 blocking root consumer task.
