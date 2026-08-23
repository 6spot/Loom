---
task: M6-T6
issue: 167
status: in_review
depends_on: [162, 163, 164, 165, 166]
created_at: 2026-08-22
started_at: 2026-08-23
completed_at: 2026-08-23
completion_pr: none (Executor constraint)
merge_sha: candidate SHA reported in issue handoff
---
# M6-T6 — Replay/fork branch-isolation gate

Build parent history with semantic Events, logical Work transitions, explicit World-Time transitions, chronology consumption and retry noise. Reconstruct several versions, fork head/history, create grandchild, diverge branches and restart.

## Required assertions
- [x] Event replay matches semantic State; Logical Journal alone supplies World Time/future/budget.
- [x] Replay calls no resolver/entropy/cognition/provider.
- [x] Fork shares Binding and clones logical future with new Work IDs/reset operations.
- [x] Parent/child/sibling/grandchild State/Future/causality remain isolated.
- [x] Later parent commits never rewrite child.
- [x] InMemory/PostgreSQL results agree after restart.
- [x] Architecture/fmt/check/clippy/tests/rustdoc + replay/fork suites pass.

## Verification evidence
Evidence: `bash tools/test.sh --workspace --all-features` with explicit reachable `LOOM_TEST_POSTGRES_URL` on a fresh PostgreSQL 18 database; targeted `postgres_fork` and `postgres_commit` suites passed. Architecture, formatting, check, clippy and rustdoc evidence is recorded in the issue handoff.
