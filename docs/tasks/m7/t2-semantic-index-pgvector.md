---
task: M7-T2
issue: 169
status: planned
depends_on: [168]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M7-T2 — Semantic indexes + PostgreSQL pgvector projection

- Capability-owned index definitions: stable ID/owner/source/projection revision/dimensions/metric/config metadata.
- Registry + World Binding validation/discovery.
- Runtime-owned projection ports; Storage implements additive PostgreSQL18+pgvector tables/indexes.
- Projection rows identify source refs/hash/revision/model revision and vector data to detect stale rebuilds.
- Similarity queries are bounded; approximate behavior is never presented as deterministic authority.
- Deleting/rebuilding projections cannot alter Event/State/logical replay/fork.

## Acceptance
- [ ] Fresh pgvector migration and query path work.
- [ ] Dimension/revision/source mismatch is typed.
- [ ] Delete/rebuild leaves authority unchanged.
- [ ] Disabled owner disables World use.
- [ ] Standard + pgvector gates pass.

## Verification evidence
Pending.