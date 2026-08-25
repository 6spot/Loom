---
task: M6-T5
issue: 166
status: completed
depends_on: [164, 165]
created_at: 2026-08-22
started_at: 2026-08-23
completed_at: 2026-08-23
completion_pr: 225
merge_sha: 07525f68a06cffa418e988a8f324848c8dee301c
---
# M6-T5 — Ancestry-aware History and causality

- History reads visible ancestry segments bounded by each fork version plus branch-local history; do not copy Events.
- Valid causal source: own earlier Event or visible ancestor Event at/before fork boundary.
- Reject sibling, unrelated World, ancestor-future and forward-in-batch references.
- Multi-generation ordering uses EventSeq + ancestry semantics, never UUID/platform time.
- PostgreSQL queries derive visibility from explicit ancestry.

## Acceptance
- [x] Child/grandchild history visibility is exact.
- [x] Valid child→ancestor causality commits.
- [x] Sibling/unrelated/ancestor-future causality cannot commit/query.
- [x] Restart + standard gates pass.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.