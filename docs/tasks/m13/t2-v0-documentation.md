---
task: M13-T2
issue: 130
status: planned
depends_on: [103, 111, 119, 127, 129]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M13-T2 — V0 Operator / Developer Documentation

## Goal
Make the implemented V0 understandable, runnable and debuggable without relying on historical issue conversations.

## Required implementation
- Refresh README/current status from obsolete “first minimal World” language.
- Document Rust/PostgreSQL18+pgvector/blob prerequisites, migrations, server config, example Templates and CLI.
- Public-surface quickstart: create Template-backed World, Action, State/History/feed, restart, fork and provenance.
- Guides for task ledger, replay vs rerun, logical Work vs retry, ancestry/fork, World Capability binding, Runtime revisions/provenance and Agent visibility.
- Troubleshooting for migrations/config/lease/fence/Ingress idempotency/API errors.
- Ensure normative diagrams/examples match final Cargo/public-exposure architecture.

## Forbidden shortcuts
No docs encouraging Runtime/Storage bypass, stale diagrams, real secrets or claims that Studio/real LLM provider blocks Engine V0.

## Acceptance checklist
- [ ] README status/scope is current;
- [ ] clean setup/quickstart is documented;
- [ ] replay/fork/work/provenance/Agency operator guides exist;
- [ ] examples use unified API/CLI;
- [ ] links/commands are checked where practical;
- [ ] docs/rustdoc/architecture checks pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned as blocking V0 closure documentation.
