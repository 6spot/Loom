---
task: M10-T4
issue: 190
status: completed
depends_on: [156, 189]
created_at: 2026-08-22
started_at: 2026-08-24
completed_at: 2026-08-24
completion_pr: 245
merge_sha: e9e2b6ffe5e926615191f57094fe6e5085390d6b
---
# M10-T4 — Atomic Agency Wake Decision/Action commit

- Scheduler `AgencyWake` admission resolves Agency/cognition target, never Capability WorkHandler.
- Build context/run cognition outside DB authority transaction, then interpret Decision under same pinned Session.
- `Act` re-enters ordinary World Binding + Action schema/resolver/subresolution/validation path; Agent origin is provenance, not hidden input.
- Optional Action Events/Effects + current Wake `Pending->Completed` + chronology consumption commit atomically under one version/fence.
- `NoAction` completes Wake with no World Event/State mutation.
- **V0 R-1:** semantic `Rejected` Act MUST complete current Wake as determined no-world-change. A later reconsideration schedules a new Wake; the rejected head cannot remain Pending.
- Technical cognition/runtime failure does not complete Wake and uses bounded FailurePolicy.

## Acceptance
- [x] Act uses normal Action authority.
- [x] Action+Wake completion+budget are atomic.
- [x] NoAction and semantic Rejected complete without fake Events.
- [x] Rejected Wake cannot head-block forever.
- [x] Technical failure remains Pending/retriable; stale CAS/fence cannot partially commit.
- [x] PostgreSQL/InMemory + standard gates pass.

Architecture: A0003 §§3.2/3.5; R-1 V0 policy fixed by this replan.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.