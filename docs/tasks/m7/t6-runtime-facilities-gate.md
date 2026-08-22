---
task: M7-T6
issue: 87
status: planned
depends_on: [82, 83, 84, 85, 86]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M7-T6 — Reaction / Entropy / Scheduler Gate

## Goal
Prove Runtime can autonomously persist/resume future execution without losing reaction obligations or hiding nondeterminism.

## Required verification
Action → Event A → atomically persisted Reaction Work W1 → stop Runtime → restart → scheduler claims W1 → handler commits Event B; include later reaction generation, concurrent workers, lease expiry/stale fencing/retry and deterministic entropy whose samples are recorded while replay never resamples.

## Acceptance checklist
- [ ] Event + reaction Work is all-or-nothing;
- [ ] Pending Work survives restart and claim-next does not double-claim;
- [ ] platform retry timing never advances World Time;
- [ ] deterministic entropy/provenance/replay contract passes;
- [ ] reaction Work remains correct under logical-history/fork contracts;
- [ ] final InMemory/PostgreSQL/architecture/fmt/check/clippy/tests/rustdoc candidate is green.

## Completion evidence
- PR:
- merge SHA:
- final candidate / CI:

## Progress log
- 2026-08-22 — Planned as M7 SERIAL GATE.
