---
task: C1-T9
issue: 498
status: in_progress
depends_on: [C1-T2]
created_at: 2026-09-04
started_at: 2026-09-04
completed_at:
completion_pr:
merge_sha:
---

# Chronicle React/Vite and shadcn Web Foundation

## Canonical scope

GitHub Issue #498 is the executable specification.

## Goal

Create one React/TypeScript/Vite application with Chronicle-specific public styling and a route-separated shadcn/ui Studio shell while preserving C0 public flows.

## Acceptance

- [x] one web build serves public and Studio routes.
- [x] Studio uses shadcn/ui without constraining public visual design.
- [x] Studio routes/API access respect server authentication.
- [x] C0 Timeline/Event/Entity/Search flows remain usable.
- [x] Studio code is route-split where practical.
- [x] frontend has no direct DB/artifact authority.
- [x] frontend build/tests/headless smoke pass.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-04 — Implementation started (ME-356): one Vite/React/TS app in `apps/chronicle/webapp/` (React Router + TanStack Query, lazy Studio routes, vendored shadcn-style Studio foundation, ported Chronicle public styles); build output committed to `apps/chronicle/web/dist/` for compile-time embed by `chronicle-server` (legacy C0 assets retained).
- 2026-09-04 — Implementation complete on feature branch, self-checks green: webapp `npm test` 11/11 + `npm run build` + `smoke:dist` PASS; `chronicle-server` `cargo test` 31/31 + clippy + fmt PASS; C0 `node --test` 12/12 + read_api unittest 21/21 PASS; Playwright+Chromium visual verification 24/24 checks PASS (public Timeline/Event/Entity/Search + Studio login/home/Imports/Review/Sources, screenshots in `webapp/scripts/visual/`, git-ignored regenerable artifacts). Delivery PR opened; awaiting review/merge + post-merge ledger reconciliation (status stays `in_progress` until then).
