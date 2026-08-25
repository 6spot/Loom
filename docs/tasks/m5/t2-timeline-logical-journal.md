---
task: M5-T2
issue: 154
status: completed
depends_on: [153]
created_at: 2026-08-22
started_at: 2026-08-23
completed_at: 2026-08-23
completion_pr: 216
merge_sha: 587672c63cb13f4808d14495054b67b5a0e3a799
---
# M5-T2 — Timeline Logical Journal

## Contract
- Runtime-owned journal records before/after TimelineVersion, explicit World-Time transitions, logical Work schedule/cancel/complete/dead, logical order and chronology-budget consumption.
- Event+State, logical Work and time transitions use the single relevant logical revision.
- Successful Scheduler Work completion and budget consumption are in the same Logical Commit; no extra counter revision.
- Claim/retry/lease/backoff/error changes append no logical history and advance no TimelineVersion.
- PostgreSQL journal persistence is atomic with the authority mutation; provide deterministic historical reads.

## Acceptance
- [x] Event-only/Work-only/time-only/Event+Work version behavior is exact.
- [x] Operational retry creates zero journal rows.
- [x] Rollback keeps authority+journal atomic.
- [x] Restart reads are deterministic.

Architecture: Amendment 0002 §3; Amendment 0003 §5.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.

## Progress Log
- 2026-08-22 — Planned.