---
task: M4-T3
issue: 148
status: in_progress
depends_on: [147]
created_at: 2026-08-22
started_at: 2026-08-22
completed_at:
completion_pr:
merge_sha:
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

- [ ] Template revisions affect future Worlds only.
- [ ] Failure matrix leaves no partial World.
- [ ] Successful World is immediately executable via Binding-aware Action path.
- [ ] InMemory/PostgreSQL parity + standard gates pass.

Architecture basis: Amendment 0001 §7; Architecture Index rows for Template placement.

## Verification evidence

Pending.

## Progress Log

- 2026-08-22 — Planned.
- 2026-08-22 — Started implementation within the existing `loom-api`/`loom-runtime`/`loom-storage` boundaries; scope limited to frozen Template descriptors, Runtime birth-plan validation, and atomic birth persistence.
