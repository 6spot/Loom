---
task: C1-T9
issue: 498
status: completed
depends_on: [C1-T2]
created_at: 2026-09-04
started_at: 2026-09-04
completed_at: 2026-09-04
completion_pr: 512
merge_sha: 13f44b720e11d9cfe8dcc943e33890feca0ff7af
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
- 2026-09-04 — Implementation added one Vite/React/TypeScript app in `apps/chronicle/webapp/`, React Router public routes, TanStack Query server state, lazy Studio routes, vendored shadcn-style Studio foundation, Chronicle-specific public styles, and deterministic build output embedded by `chronicle-server` while legacy C0 assets remain allowlisted.
- 2026-09-04 — Review findings addressed Unicode-safe Basic auth encoding and public nav layout spacing; webapp/server/C0/read-api suites and Playwright desktop/mobile smoke were rerun on the delivery candidate.
- 2026-09-04 — Delivery PR #512 merged as `13f44b720e11d9cfe8dcc943e33890feca0ff7af`. Exact delivery head `c70728b52f706f17b04fc88fc6297e93e126c979` passed GitHub Actions Chronicle run 33861253117, Chronicle Docker run 33861252991, and CI run 33861253003. Catch-up post-merge reconciliation records the already-delivered task as completed on the canonical ledger.
