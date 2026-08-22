---
task: M13-T3
issue: 131
status: planned
depends_on: [127, 129]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M13-T3 — V0 Quality and Property-Test Gates

## Goal
Strengthen critical invariants with dependency/security checks and reproducible bounded property tests.

## Required implementation
- Add `cargo deny`/approved advisory-license-dependency CI policy without weakening architecture checks.
- Bounded reproducible property tests for replay determinism, fork isolation, EventSeq/TimelineVersion continuity, causal DAG/visibility, CAS conflicts, Work fencing and Ingress idempotency.
- Preserve failing seeds/regressions and deterministic serialization/order tests where useful.
- Integrate into long-lived CI; document scoped exceptions with reason/expiry.

## Forbidden shortcuts
No replacing scenario tests with properties only, flaky unseeded CI, blanket advisory ignores or architecture-check weakening.

## Acceptance checklist
- [ ] deny/security/license gate runs in CI;
- [ ] bounded generators cover listed invariants;
- [ ] failing seeds are reproducible;
- [ ] existing scenario/integration suites remain;
- [ ] CI policy/exceptions are documented;
- [ ] architecture/fmt/check/clippy/tests/rustdoc/deny pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned as blocking V0 hardening.
