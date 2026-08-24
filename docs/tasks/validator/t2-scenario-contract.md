---
task: VAL-T2
issue: 254
status: in_progress
depends_on: [253]
created_at: 2026-08-24
started_at: 2026-08-25
completed_at:
completion_pr:
merge_sha:
---
# VAL-T2 — Stable validator scenario contract

Define the stable contract used by current and future validator scenarios.
Scenario identity is explicit data, independent of Rust implementation names;
the registry and runner preserve deterministic, public-consumer validation
semantics.

## Acceptance

- [ ] Duplicate scenario IDs are rejected.
- [ ] Registry enumeration and metadata collections are deterministic.
- [ ] Missing prerequisites are represented as `skip-unavailable`, never as
  `pass` in serialized results.
- [ ] Findings contain scenario, expected, actual, backend/context, and
  evidence references without remediation or suggested-fix authority fields.
- [ ] The runner delegates through an extensible executor contract without
  scenario-specific branching.
- [ ] Contract tests and standard Rust gates pass.

## Scope

- Stable scenario metadata and IDs under `apps/loom-validator`.
- Deterministic registry insertion, enumeration, and lookup.
- Explicit scenario result states and observational finding payloads.
- A backend-aware executor seam for future scenario implementations.

No Runtime, Storage, SQL, transport implementation authority, remediation
policy, or Task Ledger status transition is part of this task.

## Progress Log

- 2026-08-25 — Implemented the stable metadata, registry, result/finding, and
  executor contracts after VAL-T1.

## Verification Evidence

Evidence is recorded by the implementation handoff and must be confirmed by
review before this task record is marked completed.
