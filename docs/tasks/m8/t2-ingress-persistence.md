---
task: M8-T2
issue: 175
status: completed
depends_on: [174]
created_at: 2026-08-22
started_at: 2026-08-23
completed_at: 2026-08-23
completion_pr: 231
merge_sha: 9d51e4ff3be0e626389fe28a901155d1fdfb3ed3
---
# M8-T2 — Durable idempotent Ingress persistence

- Runtime-owned port + PostgreSQL records for ID/key scope, canonical request fingerprint, source/target/auth metadata, received Platform Time, lifecycle/lease/retry/error and completion refs.
- Atomic accept-or-return-existing; same key/different canonical request = conflict.
- Acceptance/claim/retry is operational only: no TimelineVersion/Event/logical history.
- Operational worker claim/fence is restart/concurrency safe.
- Source/received time never substitutes for World Time.
- Preserve origin metadata for `ExecutionOrigin::Ingress`.

## Acceptance
- [x] Idempotency across restart/concurrency.
- [x] Mismatch conflicts.
- [x] Accepted-only record mutates no World/logical state.
- [x] Fence-safe retry + InMemory/PostgreSQL parity pass.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.