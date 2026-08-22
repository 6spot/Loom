---
task: M11-T2
issue: 194
status: planned
depends_on: [193]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M11-T2 — Property/fault/dependency-security gates

- Add cargo-deny or approved equivalent for advisories/licenses/banned/duplicate dependencies with narrow documented exceptions.
- Deterministic bounded property tests for EventSeq/TimelineVersion, semantic/logical replay, fork isolation/causality, Work order/fence, chronology, Ingress idempotency and Session pinning.
- Fault injection around PostgreSQL commit rollback, Event↔Session, Ingress crash window, scheduler claim/complete/retry, Template birth and fork.
- Preserve reproducible failing seeds/regression cases and serialization/stable-order tests.
- Integrate into long-lived CI only.

## Acceptance
- [ ] Security/license/dependency gate reproducible.
- [ ] Listed authority invariants have property/fault coverage.
- [ ] Failures are locally reproducible; focused scenarios remain.
- [ ] CI partition/runtime documented and standard gates pass.

## Verification evidence
Pending.