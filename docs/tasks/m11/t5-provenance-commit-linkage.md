---
task: M11-T5
issue: 117
status: planned
depends_on: [115, 116]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M11-T5 — World Commit / Provenance Event Linkage

## Goal
Guarantee every committed Event is traceable to its producing Execution Session/Runtime Revision without weakening commit atomicity.

## Required implementation
- Extend Runtime-owned commit/provenance persistence so session→EventRef links share the required transaction/linearization guarantee.
- Link only frozen Event IDs produced by current session; cover Work and Reaction paths.
- Work-only/no-change/rejection finalizes provenance without fake Event links.
- Close any crash window that could leave a permanently committed orphan Event.
- Support EventRef→Session and Session→EventRefs query directions.

## Forbidden shortcuts
No post-commit best-effort link, session id hidden in Event payload, causality conflation or storage-generated synthetic session.

## Acceptance checklist
- [ ] committed Event resolves to exactly one producing session per contract;
- [ ] session lists all committed EventRefs deterministically;
- [ ] Work/Reaction linkage is correct;
- [ ] no-change/rejection has no fake Event;
- [ ] rollback cannot orphan Event/provenance;
- [ ] adapter/restart/architecture gates pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after durable provenance.
