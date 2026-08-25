---
task: M5-T7
issue: 159
status: completed
depends_on: [150]
created_at: 2026-08-22
started_at: 2026-08-23
completed_at: 2026-08-23
completion_pr: 217
merge_sha: 0c8ca1c4b801d5d7db0c4a5c6ca3dc9182f12b45
---
# M5-T7 — Runtime-controlled entropy

## Contract
- Runtime mediates entropy requests; Capability/Agency get no raw RNG/clock/provider handle.
- Entropy environment is pinned in the Execution Session/Assembly and shared by subresolution policy.
- Record ordered request/sample evidence for M9 provenance.
- Enforce configurable request/count/byte limits.
- Replay/fork reconstruction never resamples entropy.
- Production entropy source is composed outside semantic crates; deterministic fake supports tests.

## Acceptance
- [x] Deterministic source is reproducible.
- [x] Session evidence records ordered samples.
- [x] Budget failure cannot partially commit.
- [x] Replay performs zero entropy calls.
- [x] Architecture + standard gates pass.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.
