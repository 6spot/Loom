---
task: M5-T6
issue: 158
status: planned
depends_on: [153, 154, 157]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M5-T6 — Atomic Reaction Work scheduling

## Contract
- Event Trigger means registered Reaction → Immediate Durable Work, never recursive handler execution.
- Match only semantics enabled by World Binding.
- Reaction Work effective due is current pinned World Time and receives Runtime-assigned logical order.
- Triggering Event + generated Work + journal transitions persist atomically.
- Carry causal Event/origin references while keeping execution provenance separate from World causality.
- Validate handler/schema/Binding before commit; fan-out participates in existing budgets.

## Acceptance
- [ ] Event+Reaction Work are all-or-nothing.
- [ ] Same-time fan-out order is deterministic.
- [ ] Failure leaves no partial Event/Work.
- [ ] Reaction chain is bounded and head-ordered.
- [ ] Restart + standard gates pass.

Architecture: Amendment 0001 §8.2 + chronology rules.

## Verification evidence
Pending.