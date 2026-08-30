---
task: VALR-T20
issue: 325
status: completed
depends_on: [324]
created_at: 2026-08-27
started_at: 2026-08-27
completed_at: 2026-08-29
completion_pr: 384
merge_sha: 103a75e96cd9f7b9e495a39bb6608316c47b76e6
architecture_decision_blocker: false
---

# VALR-T20 — PostgreSQL 18 live capability matrix gate

## Completion record

T20 is complete. PR #384 merged as `103a75e96cd9f7b9e495a39bb6608316c47b76e6` and established the accepted PostgreSQL 18 live-matrix gate.

Evidence:

- evidence head: `d6654ca09d0c9d46701288054090a9bcbddc31af`
- CI run: `33250772703` — success
- the T20 matrix reported 10/10 trusted live PostgreSQL rows passing
- later current-main certification may reuse the gate implementation but must re-run it on the new production candidate; the old candidate result is historical evidence only

The previous `in_progress` frontmatter was stale task metadata, not an unresolved T20 implementation.

## Acceptance

- [x] PostgreSQL 18 live gate exists and fails closed.
- [x] Required live rows and restart evidence are exercised.
- [x] Artifact/report production is deterministic.
- [x] Required CI passed and merge evidence is recorded.
