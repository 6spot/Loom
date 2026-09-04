---
task: C1-T7
issue: 496
status: completed
depends_on: [C1-T6]
created_at: 2026-09-04
started_at: 2026-09-04
completed_at: 2026-09-04
completion_pr: 517
merge_sha: 414f75df6528ea119a664ac17fba6bc11b0726d2
---

# Chronicle Source Assembly and Within-Book Resolution

## Canonical scope

GitHub Issue #496 is the executable specification.

## Goal

Assemble many validated chunk outputs into one C0-compatible source bundle while conservatively resolving cross-chunk duplication and preserving ambiguity.

## Acceptance

- [x] one coherent source bundle is produced from many chunk outputs.
- [x] source/evidence/chunk/run provenance remains traceable.
- [x] repeated cross-chunk identities/occurrences can be conservatively linked without canonical assignment.
- [x] boundary-induced duplicate extraction is detected/controlled.
- [x] ambiguous cases remain distinct/reviewable.
- [x] unchanged accepted inputs produce deterministic assembly output/report.
- [x] C0 bundle/schema/evaluator compatibility remains green.
- [x] Chronicle CI passes.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-04 — Implementation added deterministic revision-scoped assembly, temp-ID remapping, source/evidence/chunk/run provenance, boundary duplicate suppression, conservative within-book Entity/Event links using C0 decision vocabulary, and real worker `assemble` output recording.
- 2026-09-04 — Delivery PR #517 merged as `414f75df6528ea119a664ac17fba6bc11b0726d2`. Exact delivery head `9ce38a503d708873811a6cf8782cb8d005bae5a0` passed GitHub Actions Chronicle run 33877136469 and Chronicle Docker run 33877136630. Unit/PostgreSQL acceptance in the delivery covered deterministic assembly, duplicate control and C1-T6 end-to-end extraction compatibility. Catch-up post-merge reconciliation records the already-delivered task as completed on the canonical ledger.
