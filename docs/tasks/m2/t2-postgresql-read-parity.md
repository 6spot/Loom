---
task: M2-T2
issue: 27
status: planned
depends_on: [26]
created_at: 2026-08-21
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M2-T2 — PostgreSQL WorldStore and Snapshot/Read Parity

## Goal

Implement PostgreSQL-backed Runtime read ports so pinned Timeline snapshots expose the same authoritative World/current-state/history semantics as the Milestone 1 in-memory adapter.

## Scope

- Implement PostgreSQL `WorldStore`/snapshot reads through Runtime-owned contracts.
- Reconstruct TimelineVersion and World Time exactly.
- Load current Entity/Relationship structure and entity/relationship Facets.
- Load committed Event history/order and structural/causal references required by Runtime/API inspection.
- Keep SQLx/PgPool inside `loom-storage`.
- Never infer authoritative Event order from UUID or database timestamps.

## Acceptance checklist

- [ ] empty Timeline snapshot parity;
- [ ] Entity/Relationship/Facet snapshot parity;
- [ ] Event history and EventSeq ordering parity;
- [ ] World Time and TimelineVersion parity;
- [ ] ended Relationship/current-state semantics match Milestone 1;
- [ ] missing Timeline maps to the expected typed Runtime-facing error;
- [ ] architecture, fmt, check, clippy, tests and rustdoc pass.

## Completion evidence

- PR:
- merge SHA:
- CI / verification:
- notes:

## Progress log

- 2026-08-21 — Task record created from issue #27; status `planned`.
