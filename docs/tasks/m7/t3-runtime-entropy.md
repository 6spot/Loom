---
task: M7-T3
issue: 84
status: planned
depends_on: [82]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M7-T3 — Runtime-Controlled Entropy

## Goal
Provide explicit controlled nondeterminism without giving Capability code raw randomness or changing replay semantics.

## Required implementation
- Define Runtime/host `EntropySource`, request/sample contracts and deterministic test adapter.
- Capability requests samples only through host boundary; production source is injected at composition.
- Capture every sample in execution-local provenance for M11.
- Add appropriate entropy call/byte budgets.
- Replay consumes frozen committed Effects and never resamples entropy.

## Forbidden shortcuts
No `thread_rng`/OS RNG in Capability, randomness in persistence, replay resampling or provider/RNG types in public API.

## Acceptance checklist
- [ ] deterministic source makes tests reproducible;
- [ ] samples are provenance-visible;
- [ ] Capability sees host request/sample only;
- [ ] replay never consults EntropySource;
- [ ] failure/budget behavior is deterministic;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned; parallel-safe after #82.
