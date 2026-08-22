---
task: M8-T2
issue: 175
status: planned
depends_on: [174]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M8-T2 — Durable idempotent Ingress persistence

- Runtime-owned port + PostgreSQL records for ID/key scope, canonical request fingerprint, source/target/auth metadata, received Platform Time, lifecycle/lease/retry/error and completion refs.
- Atomic accept-or-return-existing; same key/different canonical request = conflict.
- Acceptance/claim/retry is operational only: no TimelineVersion/Event/logical history.
- Operational worker claim/fence is restart/concurrency safe.
- Source/received time never substitutes for World Time.
- Preserve origin metadata for `ExecutionOrigin::Ingress`.

## Acceptance
- [ ] Idempotency across restart/concurrency.
- [ ] Mismatch conflicts.
- [ ] Accepted-only record mutates no World/logical state.
- [ ] Fence-safe retry + InMemory/PostgreSQL parity pass.

## Verification evidence
Pending.