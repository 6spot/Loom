---
task: M11-T4
issue: 196
status: planned
depends_on: [180, 194, 195]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M11-T4 — Worker/executor stress + Linux CI hygiene

- Stress independent Timeline heads, Actions, Scheduler Work, Ingress and Agency; prove Session/context/provenance isolation.
- Kill/restart around claims/commits/Session/Ingress/SSE/cognition; stale fences/CAS losers harmless.
- Audit coherent Send/Sync requirements across API futures, Runtime ports, Capability/Agency SPIs, Storage adapters and app state; no isolated alias patch as proof.
- Ubuntu/Linux is required CI baseline; remove/avoid required macOS jobs.
- Safe path filtering lets docs/task-only changes skip irrelevant expensive Rust/PostgreSQL work while relevant code/config/migration/test/workflow changes run mandatory gates.
- No disposable verifier workflows.

## Acceptance
- [ ] Multi-worker/process stress preserves authority invariants.
- [ ] Restart failures recover deterministically.
- [ ] Coherent topology compiles/runs and is documented.
- [ ] CI path filtering/macOS removal is correct.
- [ ] Relevant-code mandatory gates remain enforced.

Architecture: A0002 §4; A0003 §7.

## Verification evidence
Pending.