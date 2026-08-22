---
task: M6-T6
issue: 167
status: planned
depends_on: [162, 163, 164, 165, 166]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M6-T6 — Replay/fork branch-isolation gate

Build parent history with semantic Events, logical Work transitions, explicit World-Time transitions, chronology consumption and retry noise. Reconstruct several versions, fork head/history, create grandchild, diverge branches and restart.

## Required assertions
- [ ] Event replay matches semantic State; Logical Journal alone supplies World Time/future/budget.
- [ ] Replay calls no resolver/entropy/cognition/provider.
- [ ] Fork shares Binding and clones logical future with new Work IDs/reset operations.
- [ ] Parent/child/sibling/grandchild State/Future/causality remain isolated.
- [ ] Later parent commits never rewrite child.
- [ ] InMemory/PostgreSQL results agree after restart.
- [ ] Architecture/fmt/check/clippy/tests/rustdoc + replay/fork suites pass.

## Verification evidence
Pending.