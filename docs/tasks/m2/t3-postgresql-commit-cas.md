---
task: M2-T3
issue: 28
status: planned
depends_on: [26]
created_at: 2026-08-21
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M2-T3 — PostgreSQL CommitStore Atomic Timeline CAS and Materialization

## Goal

Implement PostgreSQL `CommitStore` so a Runtime-owned `ValidatedResolution` becomes authoritative World Truth through one short atomic transaction without changing Milestone 1 semantics.

## Scope

- Expected TimelineVersion CAS and per-Timeline contiguous EventSeq.
- Event ledger plus participants, Relationship refs and causal links.
- Ordered World Effect materialization into current Entity/Relationship/Facet state.
- Atomic Work schedule/cancel/current completion with Event/State commit.
- Preserve same-Event structural reference rules, true NoChange, zero-Effect Event and zero-Event Work semantics.
- Any stale CAS, hard-constraint or Work failure leaves no partial mutation.

## Acceptance checklist

- [ ] successful multi-Event commit assigns contiguous EventSeq and advances once;
- [ ] concurrent stale CAS produces exactly one winner and no partial mutation;
- [ ] Event + State + Work changes roll back together on failure;
- [ ] same-Event Entity/Relationship reference cases match Milestone 1;
- [ ] later-Event forward structural reference remains rejected;
- [ ] zero-Effect Event, true NoChange and zero-Event Work semantics match Milestone 1;
- [ ] Runtime and PostgreSQL hard validation agree on parity fixtures;
- [ ] architecture, fmt, check, clippy, tests and rustdoc pass.

## Completion evidence

- PR:
- merge SHA:
- concurrency / atomicity verification:
- CI / verification:
- notes:

## Progress log

- 2026-08-21 — Task record created from issue #28; status `planned`.
