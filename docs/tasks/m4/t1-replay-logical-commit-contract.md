---
task: M4-T1
issue: 61
status: planned
depends_on: []
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M4-T1 — Freeze Replay and Logical-Commit Semantics

## Goal

Freeze the authority contract for deterministic World replay and reconstruction of historical logical Durable Work before implementation proceeds.

## Implementation contract

- Replay applies committed frozen `WorldEffect`s only; it never invokes current resolvers, Capability implementations, cognition, entropy, network/provider calls or platform clocks.
- `TimelineVersion` is the logical reconstruction/fork position.
- Normatively separate World History (Events/frozen Effects), Runtime Logical Future History (Work schedule/cancel/complete) and Platform Operational History (claim/lease/fence/retry/backoff).
- Define Event-only, Work-only, Event+Work and true `NoChange` version/journal behavior.
- Define Runtime-owned replay/logical-commit types/ports only where implementation evidence needs them and specify how Pending Work is reconstructed at an arbitrary historical version.

## Forbidden shortcuts

- Do not move Runtime authority/history types into `loom-core` or `loom-api` for convenience.
- Do not turn Work retry/lease/fence metadata into World Events/history.
- Do not define replay as rerunning historical code.
- Do not expose Timeline fork in this task.

## Acceptance checklist

- [ ] normative docs define replay inputs/outputs and truth boundaries;
- [ ] historical Pending Work reconstruction is explicit;
- [ ] `NoChange`, Event-only, Work-only and mixed commits have defined version behavior;
- [ ] type/port ownership preserves the governance DAG;
- [ ] focused contract/doc tests cover introduced abstractions;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence

- PR:
- merge SHA:
- verification:

## Progress log

- 2026-08-22 — Planned as the M4 SERIAL ROOT; downstream replay/fork work must implement this contract rather than redesign it.
