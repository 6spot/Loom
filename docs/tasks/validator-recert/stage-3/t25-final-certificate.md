---
task: VALR-T25
issue: 330
status: in_progress
depends_on: [326, 328, 329]
architecture_decision_blocker: true
created_at: 2026-08-30
started_at: 2026-08-30
completed_at:
completion_pr:
merge_sha:
---

# VALR-T25 — Final current-main V0 certification decision

## Decision

**BLOCKED — no green current-main V0 certificate is published.**

T25 consumed the completed Stage-3 inputs on the same production candidate
`103a75e96cd9f7b9e495a39bb6608316c47b76e6`. Core and PostgreSQL evidence are
green, and the Validator evidence is trustworthy, but the authoritative T22
manifest still contains two blocking formal-observability gaps: `CV-028` and
`CV-029`. Under the T25 stop rule, those gaps prohibit final certification and
Root #302 closure.

This record is the required fail-closed final decision. It does not change
production code, scenario semantics, acceptance criteria, Runtime/Storage
authority, or public API surface to manufacture a certificate.

## Certified-baseline identity

Production candidate under evaluation:

- candidate SHA: `103a75e96cd9f7b9e495a39bb6608316c47b76e6`;
- source: PR #384 merge / VALR-T20 current-main PostgreSQL 18 evidence baseline;
- T20 CI: run `33250772703`, trusted PostgreSQL 18 live matrix `10/10 Pass`;
- evidence-only descendants preserve the candidate because their reviewed
  changes are task/evidence/governance records or certification tooling and do
  not change the certified production behavior.

Current Stage-3 evidence lineage consumed by this decision:

| Input | Evidence | Disposition |
| --- | --- | --- |
| T21 / #326 | PR #385 merge `4b134f391c307915da28df5846108210467dd1e3` | current-status/history reconciliation complete |
| T22 / #327 | PR #386 merge `322a9268648d243abd6196f508f5c88681c0c6a1` | authoritative current-main manifest: 38 ready, 2 gaps |
| T23 / #328 | PR #388 merge `7334c1ec10ac994546ffabe373abcdf0f023a154`; evidence head `8c5ee0f9afda9a5a20c196691af01097e6da5dd4`; CI `33264160549` success | full core V0 integrated gate PASS on fresh PostgreSQL 18; gaps preserved, not reclassified |
| T24 / #329 | PR #387 merge `f0cf50061b31e9f5e5a595ddaa9c71a4eff554d2`; evidence head `a45ed079637644e02e1d72d9a0025ea1723adae1`; CI `33262635979` success | trustworthy Validator gate: 38 Pass / 2 Unavailable, `gate_passes=false` |
| T24 durable reconciliation | PR #389 merge `f7644e1421bebf11f09ae16487a6ac3824258a4b`; CI `33267041890` success | task completion evidence reconciled without changing the gate result |

Historical M13 candidate/merge evidence remains historical. Nothing in this
record rewrites an old candidate SHA, PR, merge, or historical result into
current certification evidence.

## What is implemented and proven

The implementation/evidence work that can be completed inside the existing
architecture is already present and exercised:

- current core/runtime/storage/build/security gates pass;
- repository-controlled PostgreSQL 18 contract and required-live gates pass;
- all ten T20 required-live CV rows pass with trusted PostgreSQL evidence;
- current Validator execution remains single-pass, strict/fail-fast semantics
  remain separated and fail-closed, external evidence cannot masquerade as
  PostgreSQL, and reconnect-only cannot masquerade as real restart;
- the current 40-row Validator certification report is deterministic and
  truthful: 38 `Pass`, exactly 2 `Unavailable`, no false-green conversion;
- controlled T15 fixtures already drive semantic projection
  register/query/delete/rebuild behavior and BlobStore present/missing/corrupt
  behavior while public History/Facet/Timeline observations prove World Truth
  is unchanged.

The final two rows are therefore not missing because the test driver was not
implemented. They are blocked because the required fact cannot be observed
through an existing formal LoomClient read surface without violating the
Validator evidence policy.

## Blocking capability 1 — CV-028 semantic projection

Required claim: a semantic projection is derived/rebuildable and is not World
authority.

Already implementable with the current architecture:

- the test-only Runtime-owned projection fixture can register a semantic
  projection, rebuild it from committed state, query it, delete it, and rebuild
  it again;
- public `HistoryService::list_events`, `QueryService::get_facet`, and
  `TimelineService::inspect_timeline` prove authoritative World state remains
  unchanged around those operations.

What cannot currently be certified:

- there is **no existing formal semantic-projection observable through
  LoomClient** that can establish the projection operation/result itself;
- internal Runtime projection query state, projection-store state, or direct SQL
  is explicitly non-acceptance evidence under T08.

Result: `CV-028 = Unavailable`; architecture decision blocker recorded.

## Blocking capability 2 — CV-029 blob/reference fetch

Required claim: blob/reference availability failures are reported as
availability/integrity failures and do not rewrite authoritative history.

Already implementable with the current architecture:

- the test-only BlobStore fixture creates a real BlobRef, drives missing and
  corrupt content, and observes typed `NotFound` / hash-mismatch behavior;
- public `QueryService::get_facet` and `HistoryService::list_events` prove the
  reference-bearing Facet and authoritative History do not change.

What cannot currently be certified:

- there is **no existing formal blob/reference fetch observable through
  LoomClient** that can establish the missing/corrupt fetch result itself;
- internal BlobStore reads or SQL are explicitly non-acceptance evidence under
  T08.

Result: `CV-029 = Unavailable`; architecture decision blocker recorded.

## Why T25 does not add two new interfaces

Adding ad-hoc public semantic/blob endpoints inside a certification leaf would
violate the ownership and stop rules:

1. T25 forbids production/scenario changes and cannot invent architecture.
2. T08 explicitly distinguishes test-only drivers from public acceptance
   observations; internal evidence cannot be promoted to Pass.
3. T15 explicitly says to stop and record the gap when a required semantic read
   needs a new semantic decision rather than reaching into storage.
4. The missing formal observables are architecture/product-contract decisions,
   not implementation details owned by T25.

Accordingly, this decision does **not** request an automatic "add API" patch.
Planning/architecture authority must make one explicit choice before T25 can be
resumed: define an approved formal observable for the affected V0 capability,
or formally revise the certification requirement/scope. T25 cannot choose
between those outcomes on its own.

## Final acceptance status

- T21 status/governance input: **satisfied**.
- T22 manifest produced and current: **satisfied**, but contains two blocking
  gaps.
- T23 current-main core gate: **satisfied / PASS**.
- T24 trustworthy Validator gate: **satisfied as evidence execution**, result
  remains fail-closed at 38 Pass / 2 Unavailable.
- PostgreSQL-required evidence: **satisfied**, real PostgreSQL 18, no
  skip/inference substitution.
- Same production candidate discipline: **satisfied**.
- No unresolved blocking manifest gap: **NOT satisfied** (`CV-028`, `CV-029`).
- Final green certificate: **NOT published**.
- Stage-3 #305 closure: **not eligible**.
- Root #302 closure: **not eligible**.
- Issue #330 completion: **not eligible**; keep open until the architecture
  blocker is resolved and the affected evidence is rerun.

## Resume condition

T25 may resume only after an explicit architecture/planning decision resolves
both formal-observability gaps and the affected T22/T24 evidence is rerun on a
candidate relationship that preserves the certification discipline. Until
then, this task remains in progress with
`architecture_decision_blocker: true`; no dependent/root closure may be
unlocked from this record.
