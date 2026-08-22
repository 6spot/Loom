---
task: M4-T5
issue: 150
status: planned
depends_on: [147, 149]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M4-T5 — Root Execution Session and exact Execution Assembly

## Goal

Pin every root world-affecting execution to one immutable World/Timeline/version/Binding/Runtime Revision/exact implementation assembly.

## Implementation contract

- Runtime owns Session ID/origin/context and `ExecutionAssembly`.
- Session start pins World/Timeline, TimelineVersion, Binding, active Runtime Revision, exact compatible Capability implementations and execution policy/environment.
- Action, Work, Ingress and Template bootstrap roots use exactly one Session; subresolution remains in the same assembly.
- Persist minimum Session lifecycle/origin/revision/implementation evidence now; M9 enriches evidence later.
- Running Session never switches revision/implementation if active revision changes concurrently.
- Missing compatible software before semantic execution starts consumes no technical Work attempt.

## Forbidden shortcuts

No process-global mutable current Session, mid-subresolution registry rebinding, Session World Events, or mutation of Binding to pin implementations.

## Acceptance

- [ ] Direct Action/subresolution stays in one assembly.
- [ ] Concurrent activation cannot change running Session.
- [ ] Work/Ingress/bootstrap roots use same Session contract.
- [ ] Missing software starts no execution/attempt.
- [ ] Minimum Session records survive restart and standard gates pass.

Architecture basis: `world-runtime.md` Execution Session; Amendment 0002 §5; Amendment 0003 §3.

## Verification evidence

Pending.

## Progress Log

- 2026-08-22 — Planned.