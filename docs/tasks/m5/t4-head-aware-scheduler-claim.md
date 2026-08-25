---
task: M5-T4
issue: 156
status: completed
depends_on: [153, 155]
created_at: 2026-08-22
started_at: 2026-08-23
completed_at: 2026-08-23
completion_pr: 219
merge_sha: 2aeff4816d74729bb906a57f7839395e85436d30
---
# M5-T4 — Logical-head Scheduler admission and claim

## Canonical admission
All must hold: Pending; semantic due; operationally available; no valid conflicting lease; owner enabled by World Binding; target-specific compatible implementation assembled under pinned revision/session; chronology admission permits execution.

## Contract
- Runtime chooses one logical head per Timeline by `(effective_due_world_time, logical_schedule_order)`.
- Storage atomically re-checks and claims that exact head or nothing for that Timeline.
- `SKIP LOCKED` may distribute across independent Timeline heads only; never skip same-Timeline head for later Work.
- Claim is operational only: no TimelineVersion/journal change.
- Multi-process correctness combines head-aware fencing + CAS + transactional head/quiescence re-check.

## Acceptance
- [x] Lease/backoff/missing software on head cannot let later Work pass.
- [x] Independent Timelines can claim concurrently.
- [x] One fence winner per head.
- [x] PostgreSQL concurrency tests prove no forbidden same-Timeline skip.

Architecture: Amendments 0001 §§3–4/9, 0002 §2, 0003 §3.2.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.