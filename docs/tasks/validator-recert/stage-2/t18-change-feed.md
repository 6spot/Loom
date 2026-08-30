---
task: VALR-T18
issue: 323
status: completed
depends_on: [314]
created_at: 2026-08-27
started_at: 2026-08-27
completed_at: 2026-08-27
completion_pr: 351
merge_sha: 26b65f823e5a85311fa4066f350fab81c0484991
architecture_decision_blocker: false
---

# VALR-T18 — Change Feed / SSE resumability

## Completion record

T18 is complete. PR #351 merged as `26b65f823e5a85311fa4066f350fab81c0484991` and supplied the accepted formal-client Change Feed/SSE coverage.

Evidence:

- implementation head: `5fde9a09c3da98c45ef82437e3a5d101cdeb551d`
- CI run: `33047483437` — success
- public observations use the formal client/change-feed boundary rather than direct event-table reads

The previous `in_progress` state was stale task metadata.

## Acceptance

- [x] CV-038..CV-040 formal change-feed behavior is covered.
- [x] Resume/dedup semantics remain transport observations, not alternate World authority.
- [x] Required CI passed.
- [x] Merge evidence is recorded.
