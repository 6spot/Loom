---
task: C1-T16
issue: 505
status: in_progress
depends_on: [C1-T9, C1-T12, C1-T15]
created_at: 2026-09-04
started_at: 2026-09-05
completed_at:
completion_pr:
merge_sha:
---

# Chronicle World UI and Global Historical Time Context

## Canonical scope

GitHub Issue #505 is the executable specification.

## Goal

Turn Historical Moment into Chronicle's first real public World experience with a persistent historical-time context, readable narrative and evidence-aware navigation.

## Acceptance

- [ ] selected periods such as 208 CE render a coherent grounded World page.
- [ ] global time context navigates supported periods without fabricated precision.
- [ ] Reader Presentation and source/evidence navigation work from the World page.
- [ ] uncertainty and coverage gaps remain visible.
- [ ] existing public routes remain functional.
- [ ] frontend performs no unsupported world-state inference.
- [ ] expanded-corpus headless browser flow covers World -> Event -> Entity -> evidence.
- [ ] frontend/API/Chronicle CI passes.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-05 — Started from canonical `main` only after C1-T15 delivery, post-merge Task Ledger reconciliation, and Issue #504 closure. T16 is a public presentation/time-context task only: the World page will consume the grounded C1-T15 Historical Moment/Coverage/read contracts and preserve URL-addressable historical time; frontend code must not infer territorial control, precise person location, political ownership, troop/office state, or any other unsupported complete-world-state fact.
- 2026-09-05 — Draft PR #533 added `/world`, the persistent URL-backed public historical-time bar, time-context-preserving World/Timeline/Search/Event/Entity navigation, explicit Coverage/uncertainty/authority limitations, and a reusable production-front browser smoke. The committed deterministic React/Vite `web/dist` was rebuilt from the T16 sources after 12 Vitest files / 29 tests and TypeScript/Vite build passed.
- 2026-09-05 — Expanded six-source production-shaped acceptance passed in `Chronicle T16 dev check` run #1 (`33943456856`), artifact `9962589054`: 87 canonical entities, 70 canonical events, 25 published Reader Presentations, review/resolution convergence, and a real Chromium flow `World(208) -> 赤壁 Event -> canonical Entity -> persisted evidence` with `year=208` retained across drill-down. Neighboring 209 CE rendered corpus-unrepresented semantics without asserting historical absence. The temporary validation workflow is removed before delivery Ready; final exact-head repository CI remains required.
