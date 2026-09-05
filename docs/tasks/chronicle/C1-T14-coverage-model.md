---
task: C1-T14
issue: 503
status: completed
depends_on: [C1-T13]
created_at: 2026-09-04
started_at: 2026-09-05
completed_at: 2026-09-05
completion_pr: 529
merge_sha: c2a23f93ff6e8dff69119f27e09b70783c3a22b4
---

# Chronicle Corpus Coverage Model

## Canonical scope

GitHub Issue #503 is the executable specification.

## Goal

Make time/source/domain/entity/event/presentation density and gaps explicit as a derived projection for corpus planning and public Historical Moment context.

## Acceptance

- [x] coverage is deterministically computed from persisted Chronicle data.
- [x] time/source/domain/entity/event/presentation density is inspectable.
- [x] Studio surfaces actionable sparse areas without direct SQL.
- [x] public API distinguishes sparse/unknown coverage from affirmative historical absence.
- [x] coverage cannot mutate historical authority.
- [x] first high-density corpus coverage baseline is recorded.
- [x] PostgreSQL/API/UI tests and Chronicle CI pass.

## Verification

- Delivery PR #529 merged to `main` as `c2a23f93ff6e8dff69119f27e09b70783c3a22b4` on 2026-09-05 after final exact-head `9597cb09164a28863f7dc5463afb403d4b59bb6c` passed all required checks.
- Chronicle workflow run `33938439511` (#98) completed successfully: PostgreSQL persistence and durable-worker contracts, Rust control-plane/server contracts, read-model/UI contracts, deterministic webapp build/dist parity, two-source browser smoke, and server-front/Studio smoke all passed.
- Chronicle Docker workflow run `33938439407` (#76) completed successfully, and repository CI run `33938439405` (#794) completed successfully on the same final head.
- `apps/chronicle/corpus/c1-t14/baseline.json` records the retained high-density corpus baseline. Coverage reads the latest canonical catalog/published corpus boundary and excludes staged/in-flight bundles; the PostgreSQL regression suite locks that behavior.
- Public/Studio Coverage APIs and Studio visibility preserve explicit non-authority semantics: `unrepresented`/`sparse` describe corpus representation, not historical absence/completeness, and Coverage remains a read-only derived projection.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-05 — Started from canonical `main` after C1-T13 delivery/reconciliation/Issue closure. Initial audit selected a read-only, deterministically recomputed Coverage projection rather than a persisted completeness score/table: Coverage will read Chronicle-owned PostgreSQL state, use only observed normalized event years and persisted Event `type` surfaces, expose explicit non-authority/absence semantics, and add authenticated Studio visibility plus a public API for later Historical Moment use.
- 2026-09-05 — Implemented the deterministic Coverage projection, public/Studio APIs, Studio Coverage page, baseline record, publication-boundary/no-data regressions, and Rust namespace/auth forwarding without adding a second authority or Coverage persistence table.
- 2026-09-05 — Formal PR validation initially exposed a generated-web-dist parity failure rather than a Coverage logic failure. The deterministic Vite output was synchronized (`StudioCoveragePage.js`, `StudioLayout.js`, `index.js`, `studio-api.js`), after which final head `9597cb09164a28863f7dc5463afb403d4b59bb6c` passed Chronicle #98, Chronicle Docker #76, and repository CI #794.
- 2026-09-05 — Delivery PR #529 merged to canonical `main` as `c2a23f93ff6e8dff69119f27e09b70783c3a22b4`. This reconciliation records the actual delivery evidence and marks C1-T14 completed; C1-T15 / #504 becomes READY only after this reconciliation itself reaches `main`.
