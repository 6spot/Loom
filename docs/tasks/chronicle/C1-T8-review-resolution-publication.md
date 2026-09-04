---
task: C1-T8
issue: 497
status: completed
depends_on: [C1-T7]
created_at: 2026-09-04
started_at: 2026-09-04
completed_at: 2026-09-04
completion_pr: 518
merge_sha: 3eb46f68a73c3c6bd3da9dcf11cc285828dd2b79
---

# Chronicle Review, Resolution and Canonical Publication

## Canonical scope

GitHub Issue #497 is the executable specification.

## Goal

Integrate new source bundles with existing conservative cross-source resolution, durable ReviewItems, and canonical publication without weakening C0 identity semantics.

## Acceptance

- [x] new source bundles resolve against the persisted corpus through C0 semantics.
- [x] ambiguous decisions remain explicit and reviewable.
- [x] review decisions are durable and deterministic on resume.
- [x] stable canonical identities are reused/attached correctly.
- [x] uncertain/not-same/related-occurrence boundaries remain preserved.
- [x] publication conflicts fail closed.
- [x] job outputs link exact bundle/resolution/catalog artifacts.
- [x] C0 real-data publication regressions remain green.
- [x] PostgreSQL 18/Chronicle CI passes.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-04 — Implementation added `persistence/resolve_publish.py`, C0-reusing candidate building, durable stage-gate ReviewItems, exact C0 Entity/Event decision vocabulary, deterministic review finalization, UUID-stable canonical publication and real worker `resolve`/`publish` stages. Ambiguous candidates block safely; zero-candidate jobs can publish unattended; published outputs are content-addressed and re-adopted rather than regenerated.
- 2026-09-04 — Delivery PR #518 merged as `3eb46f68a73c3c6bd3da9dcf11cc285828dd2b79`. Exact delivery head `77c5d885da8aae5e1a57405b69eabeb2e7edc107` passed GitHub Actions Chronicle run 33880270741 and Chronicle Docker run 33880270676. Delivery verification included persistence, worker, read API, C0 resolution/publication regressions and Rust control-plane tests. Catch-up post-merge reconciliation records the already-delivered task as completed on the canonical ledger.
