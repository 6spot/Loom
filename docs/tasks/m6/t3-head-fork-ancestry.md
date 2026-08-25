---
task: M6-T3
issue: 164
status: completed
depends_on: [163]
created_at: 2026-08-22
started_at: 2026-08-23
completed_at: 2026-08-23
completion_pr: 225
merge_sha: 07525f68a06cffa418e988a8f324848c8dee301c
---
# M6-T3 — Ancestry, EventRef and atomic head fork

- Persist explicit parent Timeline + exact fork-parent TimelineVersion (or equivalent immutable ancestry).
- Use Timeline-aware EventRef where cross-Timeline history/causality needs it.
- Public fork allocates new Timeline within same World and uses M6 reconstruction.
- Child shares World Binding and preserves reconstructed State/World Time/logical budget.
- Clone only Pending Work with new Work IDs; preserve target/due/relative order and reset operational lease/retry state.
- Do not copy ancestor Event rows or Sessions.

## Acceptance
- [x] Child equals source head at fork point.
- [x] Binding stays World-scoped/shared.
- [x] Work identities reset but semantic future/order preserved.
- [x] Atomic rollback + restart parity pass.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.