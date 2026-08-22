---
task: M4-T3
issue: 148
status: completed
depends_on: [147]
created_at: 2026-08-22
started_at: 2026-08-22
completed_at: 2026-08-22
completion_pr: 208
merge_sha: 50d1dd97b563cad8222e39eb2ad14de301c78a95
---

# M4-T3 — Template validation and atomic World birth

## Goal

Make the public birth path `WorldTemplate -> Runtime validation -> ValidatedWorldBirthPlan -> atomic World/Timeline/Binding/bootstrap`, keeping M3 lifecycle primitives only as lower-level building blocks.

## Implementation contract

- Stable Template descriptors/create-from-template contracts belong in `loom-api`; no `loom-template` crate.
- Runtime validates Capability dependency/compatibility/config closure and produces private `ValidatedWorldBirthPlan`.
- Plan includes semantic Binding, initial World Time and ordered bootstrap recipe.
- Semantic bootstrap runs through ordinary Action/Resolution/Event validation.
- World + initial Timeline + Binding + Template provenance + bootstrap Event/State/logical Work persist atomically.
- Rejection, validation, identity conflict or storage failure leaves no birth artifact.
- Existing Worlds never live-read later Template revisions.

## Forbidden shortcuts

No empty-World-then-multiple-bootstrap-commits, direct SQL semantic bootstrap, Template subscription, or exact implementation list as permanent Binding.

## Acceptance

- [x] Template revisions affect future Worlds only.
- [x] Failure matrix leaves no partial World.
- [x] Successful World is immediately executable via Binding-aware Action path.
- [x] InMemory/PostgreSQL parity + standard gates pass.

Architecture basis: Amendment 0001 §7; Architecture Index rows for Template placement.

## Verification evidence

- InMemory `world_creation` and `neutral_templates` suites pass Template revision, atomic birth, Binding, bootstrap Event and Session assertions.
- PostgreSQL `postgres_lifecycle` passes atomic Template birth, Binding provenance, immediate readability and rollback cases against PostgreSQL 18.
- PR #208 merged as `50d1dd97b563cad8222e39eb2ad14de301c78a95`; post-merge CI run `32576280547` passed the Rust and PostgreSQL 18 jobs.

## Progress Log

- 2026-08-22 — Planned.
- 2026-08-22 — Started implementation within the existing `loom-api`/`loom-runtime`/`loom-storage` boundaries; scope limited to frozen Template descriptors, Runtime birth-plan validation, and atomic birth persistence.
- 2026-08-22 — Accepted and merged as PR #208; post-merge CI run `32576280547` passed.
