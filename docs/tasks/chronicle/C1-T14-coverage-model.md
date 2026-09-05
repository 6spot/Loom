---
task: C1-T14
issue: 503
status: in_progress
depends_on: [C1-T13]
created_at: 2026-09-04
started_at: 2026-09-05
completed_at:
completion_pr:
merge_sha:
---

# Chronicle Corpus Coverage Model

## Canonical scope

GitHub Issue #503 is the executable specification.

## Goal

Make time/source/domain/entity/event/presentation density and gaps explicit as a derived projection for corpus planning and public Historical Moment context.

## Acceptance

- [ ] coverage is deterministically computed from persisted Chronicle data.
- [ ] time/source/domain/entity/event/presentation density is inspectable.
- [ ] Studio surfaces actionable sparse areas without direct SQL.
- [ ] public API distinguishes sparse/unknown coverage from affirmative historical absence.
- [ ] coverage cannot mutate historical authority.
- [ ] first high-density corpus coverage baseline is recorded.
- [ ] PostgreSQL/API/UI tests and Chronicle CI pass.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-05 — Started from canonical `main` after C1-T13 delivery/reconciliation/Issue closure. Initial audit selected a read-only, deterministically recomputed Coverage projection rather than a persisted completeness score/table: Coverage will read Chronicle-owned PostgreSQL state, use only observed normalized event years and persisted Event `type` surfaces, expose explicit non-authority/absence semantics, and add authenticated Studio visibility plus a public API for later Historical Moment use.
