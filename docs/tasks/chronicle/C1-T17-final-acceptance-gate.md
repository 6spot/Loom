---
task: C1-T17
issue: 506
status: in_progress
depends_on: [C1-T16]
created_at: 2026-09-04
started_at: 2026-09-05
completed_at:
completion_pr:
merge_sha:
---

# Chronicle C1 Final Acceptance Gate

## Canonical scope

GitHub Issue #506 is the executable final-gate specification. C1-T16 transitively depends on all prior C1 implementation leaves, so this gate is the serial closeout for the complete graph.

## Goal

Prove the full Book-to-Chronicle -> readable historical world loop on the supported real Debian/PostgreSQL 18 deployment with restart/retry, review, provenance, supersession and public-browser evidence.

## Acceptance

- [ ] a previously unprocessed complete text reaches Chronicle through actual Studio ingestion without hand-built staged fixtures.
- [ ] worker restart/retry resumes from durable checkpoints.
- [ ] real review workflow resolves required ambiguity without weakening uncertainty rules.
- [ ] publication preserves C0 identity/provenance invariants.
- [ ] zh-CN Reader Presentation is readable and Claim/source traceable.
- [ ] expanded corpus supports useful Historical Moment / World browsing.
- [ ] source replacement creates an auditable superseding revision.
- [ ] real Debian + PostgreSQL 18 deployment passes end to end.
- [ ] exact-candidate Rust/Python/frontend/Chronicle CI and governance checks pass.
- [ ] every prior C1 task record is canonically reconciled before this task completes.
- [ ] Root #489 can be reconciled and closed only after this task is completed on `main`.

## Progress Log

- 2026-09-04 — Planned as the C1 serial final gate. No implementation/acceptance run started.
- 2026-09-05 — Started from canonical `main` only after C1-T16 delivery, post-merge Task Ledger reconciliation, and Issue #505 closure. This gate will not treat T13–T16 deterministic model-boundary replay as live-provider evidence: final acceptance requires the operator-configured real external model provider, complete source ingestion through the actual Studio/worker path, production Docker/Compose on Debian with PostgreSQL 18, browser/World evidence, durable restart/retry, and auditable revision supersession. Production mode must remain fail-closed if the configured provider is unavailable.
