---
task: VALR-T25
issue: 330
status: in_progress
depends_on: [326, 328, 329]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at:
completion_pr:
merge_sha:
architecture_decision_blocker: false
---

# VALR-T25 — Final current-main V0 certificate

## Certificate status

**PASS — pending durable publication of this certificate PR.**

All technical and evidence prerequisites for the V0 re-certification decision have converged. This task remains `in_progress` only because the certificate itself must first merge and complete CI before its own completion metadata can be reconciled.

## Certified production candidate

- Branch/ref: `main` production baseline.
- Certified candidate SHA: `02c55a6b5c34f227abfcb732a21bf6c390e22578`.
- Origin: PR #393 merge.
- Candidate tree: `71bb8da37f55cc5b1bb4c8ed0f004f47a4ebf00e`.
- Architecture authority for the final two observation gaps: Amendment 0004, `docs/architecture/amendments/0004-derived-resource-public-read-boundary.md`.

Later commits used below are evidence/governance-only descendants. They do not alter Runtime, Storage, schema, Validator scenario semantics, capability implementations, or the certified production candidate.

## Required inputs consumed

### T21 — governance/status reconciliation

T21 is completed in `t21-status-reconciliation.md`. It preserves historical M13 and superseded candidate evidence rather than rewriting it and separates task-completion facts from later certification freshness.

### T22 — certification manifest

T22 is completed by PR #394, merge `b225d9c36662432bc4f377d8d4f29d0f1ed763fa`.

The merged manifest:

- represents exactly CV-001 through CV-040;
- is deterministic and duplicate-free;
- records **40 ready / 0 capability gap**;
- treats CV-028/CV-029 as controlled-fixture evidence whose acceptance observations use the formal `LoomClient` read boundary;
- does not turn projection/blob mutation or corruption into public production authority.

### T23 — core integrated gate

T23 is completed from PR #394 / merge `b225d9c36662432bc4f377d8d4f29d0f1ed763fa` / CI run `33288294125`.

Both required jobs completed successfully, including dependency/security policy, architecture gates, fmt/check/strict Clippy, full workspace tests, rustdoc, and the complete PostgreSQL 18 persistence contract. The production candidate also has exact-tree implementation CI from PR #393 run `33269628735`.

### T24 — trustworthy Validator certification gate

T24 is completed by PR #395, merge `411e5bf7c573d39d1e6ec9fc7ddfed4a3f4d6901`, CI run `33290303853`.

The final T24 machine artifact (`validator-t24-final-certification`, artifact id `9725902703`, digest `sha256:2b15838ebd87ce5c69163c9d487d545f29a330108917898ef2f4462ea17b7788`) records:

- candidate `02c55a6b5c34f227abfcb732a21bf6c390e22578`;
- merged T22 input `b225d9c36662432bc4f377d8d4f29d0f1ed763fa`;
- exactly 40 CV rows;
- **40 Pass / 0 Fail / 0 Unavailable**;
- `manifest_gap_count = 0`;
- all 17 command groups actually executed nonzero passing tests;
- `gate_passes = true`.

The same run completed the ordinary full workspace test gate and rustdoc successfully. Its PostgreSQL 18 job also completed successfully.

### PostgreSQL 18 required-live evidence

Real PostgreSQL 18 evidence is present; no required-live row is certified from skip, environment inference, or an unavailable result.

The T20 live matrix remains the required-live evidence authority for its frozen 10-row set, and both PR #394 (`33288294125`) and PR #395 (`33290303853`) re-executed the PostgreSQL 18 persistence/live gates successfully. T24 independently invoked the T20 gate as one of its 17 certification command groups and required its executed result to pass for T20-required CVs.

## CV-028 / CV-029 closure

The historical final gaps were semantic-projection rebuild equivalence and exact blob/reference integrity observation.

They were closed by T27 / PR #393 under Amendment 0004 using only two narrow read-only public Query operations. No public semantic projection register/rebuild/delete/write API and no public blob write/delete/list/browse API were added.

Fresh certification observes both capabilities through `LoomClient`; controlled Runtime/ProjectionStore/BlobStore access remains setup/fault-driver evidence only. The `semantic_blob` target executed 11/11 tests in the implementation and certification runs, including controlled InMemory and PostgreSQL 18 cases.

## Historical evidence boundary

Historical M13 and superseded Validator candidates remain historical facts. This certificate does not relabel old non-pass results as passes.

In particular:

- M13 candidate and integration records remain historical;
- the pre-Amendment-0004 `38 Pass / 2 Unavailable` T24 result remains a truthful historical result for its old candidate;
- historical PR #380 / cancelled T26 are not used as current acceptance evidence;
- the current PASS derives from PR #393 implementation, PR #394 current-candidate core/manifest evidence, and PR #395 final 40-CV certification.

## Residual certification gaps

**None.**

T22 contains no blocking capability gap and T24 reports all 40 CV rows as Pass. No required PostgreSQL row is skipped or unavailable. No unresolved P0/P1 Validator authority gap is hidden behind an aggregate green result.

## Tracker reconciliation state

At certificate-publication time:

- Stage 1 / #303 has all child leaves completed; tracker closure is pending final repository reconciliation only.
- Stage 2 / #304 has all child leaves completed; tracker closure is pending final repository reconciliation only.
- Stage 3 / #305 has T21, T22, T23 and T24 completed; T25 is the final remaining leaf and will become complete after this certificate PR merges and its CI evidence is durable.
- Root #302 becomes eligible for closure only after T25 completion metadata and tracker/index state are reconciled.
- T27 / #392 is implemented, independently validated, merged, and eligible for closure once the final reconciliation is durable.

## Root #302 closure checklist

- [x] Concrete production candidate SHA is fixed.
- [x] Integrated core evidence is green.
- [x] Validator evidence is trustworthy and reports 40/40 Pass.
- [x] Required PostgreSQL 18 evidence is real execution.
- [x] T22 has no unresolved certification gap.
- [x] Historical evidence remains historical rather than rewritten.
- [x] Full re-certification Task Ledger invariants are enforced in CI.
- [ ] This certificate PR has merged with successful CI.
- [ ] T25 completion metadata is reconciled from that merged publication evidence.
- [ ] Stage trackers and Root GitHub issues are closed only after the final reconciliation PR is green and merged.

## T25 acceptance

- [x] T21, T23 and T24 contain completed durable evidence.
- [x] T22 has no unresolved blocking certification gap.
- [x] Core and Validator evidence certify the same fixed production candidate through explicitly reviewed evidence-only descendants.
- [x] PostgreSQL-required evidence is real PostgreSQL 18 execution.
- [x] Exact candidate, T22/T23/T24 evidence, CI run IDs and T24 artifact identity are recorded.
- [x] Residual gaps are truthfully `none` based on the 40-row T24 report.
- [ ] Certificate publication PR and merge SHA are recorded after merge.
- [ ] Final tracker/root reconciliation CI is complete before issue closure.
