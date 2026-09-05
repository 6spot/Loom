---
task: C1-T16
issue: 505
status: completed
depends_on: [C1-T9, C1-T12, C1-T15]
created_at: 2026-09-04
started_at: 2026-09-05
completed_at: 2026-09-05
completion_pr: 533
merge_sha: 9343093e8910ebb2cebb366f386ff76a0351b8f4
---

# Chronicle World UI and Global Historical Time Context

## Canonical scope

GitHub Issue #505 is the executable specification.

## Goal

Turn Historical Moment into Chronicle's first real public World experience with a persistent historical-time context, readable narrative and evidence-aware navigation.

## Acceptance

- [x] selected periods such as 208 CE render a coherent grounded World page.
- [x] global time context navigates supported periods without fabricated precision.
- [x] Reader Presentation and source/evidence navigation work from the World page.
- [x] uncertainty and coverage gaps remain visible.
- [x] existing public routes remain functional.
- [x] frontend performs no unsupported world-state inference.
- [x] expanded-corpus headless browser flow covers World -> Event -> Entity -> evidence.
- [x] frontend/API/Chronicle CI passes.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-05 — Started from canonical `main` only after C1-T15 delivery, post-merge Task Ledger reconciliation, and Issue #504 closure. T16 is a public presentation/time-context task only: the World page consumes the grounded C1-T15 Historical Moment/Coverage/read contracts and preserves URL-addressable historical time; frontend code does not infer territorial control, precise person location, political ownership, troop/office state, or any other unsupported complete-world-state fact.
- 2026-09-05 — Delivery PR #533 added `/world`, the persistent URL-backed public historical-time bar, time-context-preserving World/Timeline/Search/Event/Entity navigation, explicit Coverage/uncertainty/authority limitations, a reusable production-front browser smoke, direct `/world` SPA refresh support in the Rust web front, and synchronized deterministic React/Vite `web/dist`. Webapp validation passed 12 Vitest files / 29 tests plus TypeScript/Vite build and dist parity.
- 2026-09-05 — Expanded six-source production-shaped acceptance passed in `Chronicle T16 dev check` run #1 (`33943456856`), artifact `9962589054`: 87 canonical entities, 70 canonical events, 25 published Reader Presentations, review/resolution convergence, and a real Chromium flow `World(208) -> 赤壁 Event -> canonical Entity -> persisted evidence` with `year=208` retained across drill-down. Neighboring 209 CE rendered corpus-unrepresented semantics without asserting historical absence. The temporary validation workflow was removed before delivery Ready.
- 2026-09-05 — Final exact-head delivery evidence for `d81dc63f156c7e090fa188d889741cde75a5a2b1`: Chronicle #115 PASS on attempt 2, including both browser smokes; attempt 1 had only a transient hosted-runner Chrome cold-start process timeout before DOM assertions and the identical-head rerun passed without changing the test. Chronicle Docker #93 PASS and CI #811 PASS. PR #533 merged to `main` as `9343093e8910ebb2cebb366f386ff76a0351b8f4`; post-merge reconciliation records C1-T16 as completed.
