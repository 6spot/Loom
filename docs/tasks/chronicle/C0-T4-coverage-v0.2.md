---
task: C0-T4
issue: 465
status: completed
depends_on: [C0-T2, C0-T3]
created_at: 2026-08-31
started_at: 2026-08-31
completed_at: 2026-09-01
completion_pr: 459
merge_sha: 2e6dec7689bccfd4fc409a4a0486824d4bcb5791
---

# Chronicle extraction coverage v0.2 experiment

## Goal

Evaluate whether a second closed-book model pass should be used to recover omissions from Chronicle model-v0 extraction.

## Decision

**Coverage v0.2 is not part of the production ingestion architecture.**

The experiments were useful because they exposed real extraction and contract problems, but progressively tightening a second semantic audit duplicated the extraction agent's core responsibility: understanding historical source text. Production work continues in C0-T5 / #466 with contract-first single extraction, deterministic validation, and bounded validator-driven repair.

Coverage code and captured measurements remain in the repository as research/debugging evidence until normal delivery cleanup; they are not the recommended execution path.

## Evidence

Refined Luna Run #1 baseline over one fixed staged bundle:

- hard failures: 0;
- entities: 14/15 gold recall (0.933);
- events: 10/12 (0.833);
- claims: 7/9 (0.778);
- counts: 27 entities / 13 events / 10 claims / 3 warnings.

Full-bundle coverage experiment:

- entities improved to 15/15;
- events improved to 11/12;
- claims regressed to 6/9;
- counts expanded to 33/29/26.

This proved a second model pass could find omitted information, including Wen Ping's appointment and Sun Quan's Hefei attack, but rewriting the bundle damaged already-good representations and caused object explosion.

Additions-only coverage preserved Run #1 exactly but proposed zero additions. Mandatory audit units then made omissions observable, but the raw audit exposed another design problem: the second pass started becoming a parallel historical parser. It proposed many new Events, omitted corresponding Claims, and assigned September to `屯襄阳` / `刘备屯樊` even though those clauses inherit August from the source.

A claim-aware/month-aware audit correctly rejected such errors, but the growing protocol complexity demonstrated that production responsibilities were becoming inverted.

## Lessons retained

- Entity presence does not imply that a source assertion is represented.
- Event and Claim are separate semantic layers.
- Event identity should be reserved for distinct occurrences/state transitions; subordinate assertions can remain Claims.
- traditional source-calendar context must not be silently shifted;
- pass-2 full-bundle rewriting can regress good pass-1 data;
- human gold belongs in evaluation, never model repair input;
- mechanically provable validation is useful; a second semantic coverage system is not the desired production abstraction.

## Acceptance

- [x] Multiple coverage strategies were implemented and measured against the same Run #1 staged output.
- [x] Full-bundle rewrite regression/object growth was measured.
- [x] Additions-only immutability behavior was measured.
- [x] Raw audit output exposed missing Claim coverage and source-month drift.
- [x] Experiment conclusion is recorded: do not adopt Coverage v0.2 in production.
- [x] Production successor C0-T5 / #466 exists.
- [x] Full prototype unittest discovery passes in a repository checkout.
- [x] Delivery PR / CI / merge reconciliation completed.

## Completion verification

The experiment remains intentionally non-production, but its retained development code continues to pass inside the complete Chronicle prototype suite. On 2026-09-01 the repository checkout ran 50 Chronicle prototype tests and finished `OK`.

Delivery PR #459 merged the experiment evidence and its production successor into `main` as `2e6dec7689bccfd4fc409a4a0486824d4bcb5791`. The current GitHub Actions path filters do not include Chronicle/Python, so no Chronicle GitHub CI pass is claimed.
