---
task: M6-T5
issue: 166
status: planned
depends_on: [164, 165]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M6-T5 — Ancestry-aware History and causality

- History reads visible ancestry segments bounded by each fork version plus branch-local history; do not copy Events.
- Valid causal source: own earlier Event or visible ancestor Event at/before fork boundary.
- Reject sibling, unrelated World, ancestor-future and forward-in-batch references.
- Multi-generation ordering uses EventSeq + ancestry semantics, never UUID/platform time.
- PostgreSQL queries derive visibility from explicit ancestry.

## Acceptance
- [ ] Child/grandchild history visibility is exact.
- [ ] Valid child→ancestor causality commits.
- [ ] Sibling/unrelated/ancestor-future causality cannot commit/query.
- [ ] Restart + standard gates pass.

## Verification evidence
Pending.