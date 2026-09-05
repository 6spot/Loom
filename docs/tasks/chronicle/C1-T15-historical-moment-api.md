---
task: C1-T15
issue: 504
status: completed
depends_on: [C1-T13, C1-T14]
created_at: 2026-09-04
started_at: 2026-09-05
completed_at: 2026-09-05
completion_pr: 531
merge_sha: 893f6f2d5ff1f6cc3a9fd2080ad9f3614e92d8db
---

# Chronicle Historical Moment Projection

## Canonical scope

GitHub Issue #504 is the executable specification.

## Goal

Expose a grounded Historical Moment projection for a selected year/period using canonical Events/Entities/places/polities, Reader Presentation and explicit Coverage without pretending to own a complete historical world state.

## Acceptance

- [x] stable Historical Moment API returns grounded canonical data for a selected period.
- [x] source/Claim traceability is preserved.
- [x] temporal precision/disagreement remains explicit.
- [x] sparse coverage is represented in the contract.
- [x] unsupported territorial/location/state facts are absent rather than inferred.
- [x] 208 CE and a neighboring period are tested on the expanded real corpus.
- [x] deterministic PostgreSQL/API/Chronicle CI passes.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-05 — Started from canonical `main` only after C1-T14 delivery, post-merge Task Ledger reconciliation, and Issue #503 closure. Initial implementation boundary is a deterministic read-only `Historical Moment Projection` over the latest published Chronicle canonical catalog, reusing Coverage absence/density semantics and persisted canonical/source/Claim/Reader Presentation data. It will not infer unsupported territorial control, precise person locations, political ownership, troop counts, or other complete-world-state facts.
- 2026-09-05 — Delivery PR #531 added the Python Historical Moment projection, public/legacy Rust forwarding, deterministic PostgreSQL and Rust integration contracts, and server API documentation. The temporary branch-only high-density acceptance workflow was removed before delivery.
- 2026-09-05 — Expanded six-source production-shaped acceptance passed with 87 canonical entities, 70 canonical events, and 25 published Reader Presentations. 208 CE returned grounded events including `赤壁之战` with Claim evidence and was deterministic across repeated requests; 209 CE explicitly reported unrepresented corpus coverage without asserting historical absence. `Chronicle T15 dev check` run #5 passed.
- 2026-09-05 — Final exact-head delivery evidence for `bf28f454de202a0e4f5358761f6575eb260310a8`: Chronicle #106 PASS, Chronicle Docker #84 PASS, CI #802 PASS. PR #531 merged to `main` as `893f6f2d5ff1f6cc3a9fd2080ad9f3614e92d8db`; post-merge reconciliation records C1-T15 as completed.
