---
task: VALR-T17
issue: 322
status: completed
depends_on: [314]
created_at: 2026-08-27
started_at: 2026-08-27
completed_at: 2026-08-28
completion_pr: 372
merge_sha: 94ebe8c3caef68e0c41ea5148dafe402bcbeb85e
architecture_decision_blocker: false
---

# VALR-T17 — Agency controlled execution evidence

## Completion record

T17 is complete. The accepted implementation is PR #372, merged as `94ebe8c3caef68e0c41ea5148dafe402bcbeb85e`.

Evidence:

- implementation head: `0179e0b8fbb6533f02afca044a80837a29349c4b`
- CI run: `33170447269` — success
- controlled test-only Agency harness covers NoAction, normal-authority Act, semantic rejection, and same-Wake CAS/fence competition
- acceptance observations are through LoomClient; no public Decision/execute/fence API was added

The earlier blocker-only state is superseded by PR #372. The previous `in_progress` frontmatter was stale metadata.

## Acceptance

- [x] CV-034..CV-037 controlled scenarios are implemented.
- [x] Product authority remains in the existing Action/Work/Runtime paths.
- [x] No unnecessary public Agency mutation API was introduced.
- [x] Required CI passed and merge evidence is recorded.
