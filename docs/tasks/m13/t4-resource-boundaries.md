---
task: M13-T4
issue: 132
status: planned
depends_on: [129, 131]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M13-T4 — Resource and Abuse Boundaries

## Goal
Make every externally/recursively amplified V0 path explicitly bounded in the correct policy layer.

## Required implementation
Freeze/configure limits for HTTP bodies, Action/Event payloads, History pages, causal depth/results/bytes, semantic results/bytes, Resolution events/effects/work/subresolution, Reaction fan-out, Agent context/cognition, SSE buffers, Ingress payload/retries and worker concurrency. Boundary rejects transport abuse early; Runtime independently enforces semantic/execution budgets for embedded callers. Server validates config and tests under/exact/over limits with no partial mutation.

## Forbidden shortcuts
No HTTP-only protection, production `usize::MAX` public paths, deployment constants in Core or silent truncation without explicit cursor contract.

## Acceptance checklist
- [ ] all amplification paths have owner/default/config;
- [ ] Runtime and Boundary independently enforce relevant limits;
- [ ] over-limit requests fail typed/no partial mutation;
- [ ] SSE/worker backpressure/concurrency tests pass;
- [ ] invalid server config fails startup;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned as blocking V0 hardening.
