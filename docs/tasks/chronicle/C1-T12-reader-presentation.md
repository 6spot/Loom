---
task: C1-T12
issue: 501
status: completed
depends_on: [C1-T8, C1-T9]
created_at: 2026-09-04
started_at: 2026-09-04
completed_at: 2026-09-05
completion_pr: 525
merge_sha: 56efb75cbcb35668d546b82fa1a241f349a8bbdf
---

# Chronicle Reader Presentation

## Canonical scope

GitHub Issue #501 is the executable specification.

## Goal

Persist one derived `zh-CN` reader-facing Event/Entity narrative layer that is readable by default and remains traceable to supporting Claims/evidence.

## Acceptance

- [x] versioned Event/Entity Reader Presentation contracts exist.
- [x] presentation is stored separately from historical authority.
- [x] presentation blocks resolve to supporting Claims/evidence.
- [x] unsupported material is omitted/fails closed rather than invented.
- [x] disagreement and uncertainty remain visible.
- [x] public Event/Entity pages are readable-first with evidence drill-down.
- [x] regeneration does not mutate canonical IDs/source Claims.
- [x] no persisted multilingual variants are required.
- [x] real examples pass grounding/readability inspection and CI.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-04 — Started from canonical `main` after C1-T11 reconciliation. T12 will add an application-owned, append-only `zh-CN` Reader Presentation projection above canonical identity/Claims: presentation versions and atomic reader blocks are derived, every published block must bind to persisted `(bundle, Claim ref)` support with evidence, regeneration creates a new projection instead of mutating canonical/source knowledge, and public Event/Entity reads become readable-first while retaining the existing evidence/resolution drill-down.
- 2026-09-04 — Implemented Reader Presentation contract v0.1, append-only PostgreSQL projection/migration, direct-Claim/evidence support triggers, versioned offline generator, input fingerprinting, disagreement/uncertainty fail-closed validation, read-model projection, reader-first Event/Entity UI with expandable Claim/evidence support, and a distinct lease-fenced worker `present` stage. The presentation provider is explicit and separate from chunk extraction; targets without direct evidenced Claims are omitted rather than filled from model knowledge, exact-input crash retries adopt the existing artifact without another model call, and cancellation/takeover during inference prevents stale prose from being published.
- 2026-09-04 — Development acceptance passed on PostgreSQL 18 and the locked webapp: persistence/read API contracts validate Claim grounding, `zh-CN`-only persistence, immutable regeneration, uncertainty preservation and request-time `null` fallback; worker integration validates offline generation, crash-window adoption and lease fencing while the full pre-existing worker suite remains green; Vitest + Vite build + dist smoke regenerated the committed reader-first bundle. Manual grounding/readability inspection is recorded in `apps/chronicle/docs/reader-presentation.md` using retained C0 Claims for 赤壁之战、刘表 and 孙权, explicitly rejecting unsupported fire-attack/causality/significance prose. Formal exact-head delivery gates are still required before completion.
- 2026-09-05 — Delivery PR #525 merged as `56efb75cbcb35668d546b82fa1a241f349a8bbdf`. Exact delivery head `6bcdcfa30b53adace3447e7510c28432022fd70c` passed Chronicle run 33894874727 and Chronicle Docker run 33894874708. Chronicle covered PostgreSQL persistence, durable worker regression including the new `present` stage, Rust control-plane/server contracts, read-model/UI/webapp contracts, retained two-source browser smoke, and Rust-front smoke; Chronicle Docker started the full stack and verified the imported historical world through HTTP. Core `CI` was correctly not triggered because the final T12 diff changes no paths selected by `.github/workflows/ci.yml`; under the repository's scoped-CI policy that gate is N/A rather than skipped work being treated as a success.
