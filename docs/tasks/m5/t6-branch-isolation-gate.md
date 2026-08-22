---
task: M5-T6
issue: 73
status: planned
depends_on: [68, 69, 70, 71, 72]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M5-T6 — Branch Isolation and Restart Gate

## Goal
Prove head/historical/multi-generation forks preserve shared past while State/Future diverge safely.

## Required verification
Create main, child, historical child and grandchild Timelines; perform divergent structural/facet/relationship/Work mutations and causal links; restart Runtime/process and compare histories, State and future obligations.

## Acceptance checklist
- [ ] fork-point State and inherited identities are exact;
- [ ] branch-created State/relationships do not leak;
- [ ] Work completion/cancellation is branch-local and cloned IDs differ;
- [ ] technical claim/retry state is not inherited;
- [ ] ancestry history/causality obeys fork boundaries;
- [ ] PostgreSQL restart and InMemory parity pass;
- [ ] final candidate passes architecture/fmt/check/clippy/tests/rustdoc/PostgreSQL gates.

## Completion evidence
- PR:
- merge SHA:
- final candidate / CI:

## Progress log
- 2026-08-22 — Planned as M5 SERIAL GATE.
