---
task: M12-T3
issue: 200
status: completed
depends_on: [151, 192, 198]
created_at: 2026-08-22
started_at: 2026-08-25
completed_at: 2026-08-25
completion_pr: 281
merge_sha: 39fb245323a485f91bd724dbae1a2e3f69c7364e
---
# M12-T3 — Neutral V0 examples

- Package neutral Capabilities/Templates covering Entity/Relationship/Facet, Action/Event, dependency/subresolution, Reaction/Work, multiple bindings, semantic retrieval/blob refs and deterministic Agent cognition.
- Examples stay concrete extension/application code; no domain behavior moves into Core/Runtime.
- Multiple Template revisions demonstrate future-World-only changes and installed-but-disabled semantics.
- User-facing setup uses public Template/API/CLI only, no direct SQL fixtures.
- Deterministic fake cognition is the supported V0 example; vendor LLMs remain non-blocking/deferred.

## Acceptance
- [x] Every major V0 public workflow has a neutral example.
- [x] Multiple bindings/Templates visibly differ.
- [x] Examples survive restart/replay/fork.
- [x] Agency example needs no vendor credentials.
- [x] Architecture/integration + standard gates pass.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.