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
- 2026-09-04 — Review D-1/D-2 addressed on PR #512: new `webapp/src/lib/basic-auth.ts` UTF-8-encodes credentials before Base64 (+ `tests/studio-auth.test.ts` ASCII/Unicode vectors); `.site-nav` gets flex + gap in `webapp/src/styles/chronicle.css`. Re-verified: webapp 14/14, server 31/31 + clippy + fmt, C0 12/12, read_api 21/21, Playwright+Chromium 27/27 (incl. nav-gap measurement and Unicode-password login against a restarted front). Pushed to PR branch; awaiting next review pass.
