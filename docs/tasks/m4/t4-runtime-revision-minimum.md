---
task: M4-T4
issue: 149
status: planned
depends_on: [147]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M4-T4 — Minimum Runtime Revision ledger

## Goal

Introduce the minimum durable Platform History needed to assemble executions correctly before the richer M9 provenance/Admin work.

## Implementation contract

- Runtime owns stable Runtime Revision descriptors and immutable publication records.
- Persist active revision selection in InMemory/PostgreSQL; activation is platform history, never a World Event.
- Revision identifies exact installed Capability implementation versions/compatibility available to an Execution Assembly.
- Server/composition explicitly registers/confirms revisions; process startup does not silently redefine semantics.
- Incompatible active software makes execution unavailable; it never mutates World Binding.

## Forbidden shortcuts

No mutable version string without history, World Event for activation, secrets in revision metadata, or mid-execution revision switching.

## Acceptance

- [ ] Immutable revision/active state survives restart.
- [ ] Selection is concurrency-safe and compatibility checks typed.
- [ ] Activation changes no World history/state/binding.
- [ ] Fresh PostgreSQL migration + standard gates pass.

Architecture basis: `evolution.md`, `world-runtime.md` Execution Session/Assembly.

## Verification evidence

Pending.

## Progress Log

- 2026-08-22 — Planned.