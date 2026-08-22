---
task: M9-T2
issue: 97
status: planned
depends_on: [96]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M9-T2 — Durable Idempotent Ingress Persistence

## Goal
Persist accepted external input and idempotency state so requests survive restart and cannot duplicate World mutation.

## Required implementation
- Runtime-owned ingress port + additive PostgreSQL schema for key scope, canonical request fingerprint, source/target, receipt time, lifecycle/attempt/error and completed result/EventRefs.
- Atomic accept-or-return-existing: same key+same request returns existing; same key+different content conflicts.
- Define recoverable processing state/lease-fencing if concurrent ingress workers are permitted.
- InMemory parity; acceptance alone creates no Event/TimelineVersion change.

## Forbidden shortcuts
No process-local production HashMap, Event append during acceptance, duplicate restart window or raw HTTP persistence contract.

## Acceptance checklist
- [ ] idempotency works across restart;
- [ ] mismatched duplicate conflicts;
- [ ] concurrent accepts yield one logical record;
- [ ] accepted state causes no World mutation;
- [ ] adapter/fresh-migration parity passes;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after #96.
