---
task: M7-T2
issue: 169
status: completed
depends_on: [168]
created_at: 2026-08-22
started_at: 2026-08-23
completed_at: 2026-08-23
completion_pr: 227
merge_sha: f3f1c3b3de1fe6b8a391e4cdbe5b42b351268364
---
# M7-T2 — Semantic indexes + PostgreSQL pgvector projection

- Capability-owned index definitions: stable ID/owner/source/projection revision/dimensions/metric/config metadata.
- Registry + World Binding validation/discovery.
- Runtime-owned projection ports; Storage implements additive PostgreSQL18+pgvector tables/indexes.
- Projection rows identify source refs/hash/revision/model revision and vector data to detect stale rebuilds.
- Similarity queries are bounded; approximate behavior is never presented as deterministic authority.
- Deleting/rebuilding projections cannot alter Event/State/logical replay/fork.

## Acceptance
- [x] Fresh pgvector migration and query path work.
- [x] Dimension/revision/source mismatch is typed.
- [x] Delete/rebuild leaves authority unchanged.
- [x] Disabled owner disables World use.
- [x] Standard + pgvector gates pass.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.