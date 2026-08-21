---
task: M2-T3
issue: 28
status: completed
depends_on: [26]
created_at: 2026-08-21
started_at: 2026-08-21
completed_at: 2026-08-21
completion_pr: 38
merge_sha: 9480211108790cb41eabf46da7b29577100205c0
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

- [x] successful multi-Event commit assigns contiguous EventSeq and advances once;
- [x] concurrent stale CAS produces exactly one winner and no partial mutation;
- [x] Event + State + Work changes roll back together on failure;
- [x] same-Event Entity/Relationship reference cases match Milestone 1;
- [x] later-Event forward structural reference remains rejected;
- [x] zero-Effect Event, true NoChange and zero-Event Work semantics match Milestone 1;
- [x] Runtime and PostgreSQL hard validation agree on parity fixtures;
- [x] architecture, fmt, check, clippy, tests and rustdoc pass.

## Completion evidence

- PR: #38
- merge SHA: `9480211108790cb41eabf46da7b29577100205c0`
- concurrency / atomicity verification: `postgres_18_commit_concurrent_cas_has_exactly_one_winner`, `postgres_18_commit_work_failure_rolls_back_event_and_state`, and `postgres_18_commit_current_work_completion_is_atomic_runtime_state` passed against PostgreSQL 18.
- CI / verification: final implementation/task-record GitHub Actions run `32456912832` — PostgreSQL 18 persistence contract success; Rust Ubuntu success; Rust macOS success; Architecture, Format, Check, Clippy, Test and Rustdoc all green.
- notes: `CommitStore` is executor-neutral Future-returning. PostgreSQL locks the Timeline row, compares the complete expected `TimelineVersion`, applies Event/State/Work mutations in one SQL transaction, assigns contiguous `EventSeq`, advances `StateRevision` once for a real runtime-state mutation, and leaves true NoChange unchanged. Same-Event Relationship references remain frozen facts even when that Event ends the Relationship, while already-ended base Relationships and later-Event forward structural references remain rejected.

## Progress log

- 2026-08-21 — Task record created from issue #28; status `planned`.
- 2026-08-21 — Implementation started on `feat/m2-t3-postgresql-commit-cas`; status `in_progress`.
- 2026-08-21 — PostgreSQL 18 run `32455635120` passed 6/7 commit parity tests but exposed a same-Event lifecycle ordering mismatch: an Event that references the active Relationship it ends was rejected after materialization marked the Relationship inactive. The storage hard boundary must preserve the Milestone 1 rule that a successfully applied `EndRelationship` in the same Event does not invalidate that Event's frozen Relationship association; already-ended base Relationships remain rejected by the Effect hard check.
- 2026-08-21 — Fixed same-Event ended-Relationship association parity, removed all temporary write-enabled CI helpers, and completed the clean final verification in run `32456637507`.
- 2026-08-21 — PR #38 merged as `9480211108790cb41eabf46da7b29577100205c0`; merge SHA recorded by the required post-merge audit.
