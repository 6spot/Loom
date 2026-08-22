---
task: M6-T3
issue: 164
status: planned
depends_on: [163]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M6-T3 — Ancestry, EventRef and atomic head fork

- Persist explicit parent Timeline + exact fork-parent TimelineVersion (or equivalent immutable ancestry).
- Use Timeline-aware EventRef where cross-Timeline history/causality needs it.
- Public fork allocates new Timeline within same World and uses M6 reconstruction.
- Child shares World Binding and preserves reconstructed State/World Time/logical budget.
- Clone only Pending Work with new Work IDs; preserve target/due/relative order and reset operational lease/retry state.
- Do not copy ancestor Event rows or Sessions.

## Acceptance
- [ ] Child equals source head at fork point.
- [ ] Binding stays World-scoped/shared.
- [ ] Work identities reset but semantic future/order preserved.
- [ ] Atomic rollback + restart parity pass.

## Verification evidence
Pending.