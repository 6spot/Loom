---
task: M5-T7
issue: 159
status: planned
depends_on: [150]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
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
- [ ] Deterministic source is reproducible.
- [ ] Session evidence records ordered samples.
- [ ] Budget failure cannot partially commit.
- [ ] Replay performs zero entropy calls.
- [ ] Architecture + standard gates pass.

## Verification evidence
Pending.