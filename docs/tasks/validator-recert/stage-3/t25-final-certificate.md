---
task: VALR-T25
issue: 330
status: completed
depends_on: [326, 328, 329]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at: 2026-08-30
completion_pr: 396
merge_sha: c443091783e5a49a0e280366bb85129af536a0bb
architecture_decision_blocker: false
---

# VALR-T25 — Final current-main V0 certificate

## Certificate status

**PASS — published and durable.**

The V0 re-certification certificate was published by PR #396 and merged as
`c443091783e5a49a0e280366bb85129af536a0bb` after exact-head CI run
`33290933514` completed both required jobs successfully. T25 is therefore
complete; this record is the post-merge metadata reconciliation of that already
completed publication.

## Certified production candidate

- Branch/ref: `main` production baseline.
- Certified candidate SHA: `02c55a6b5c34f227abfcb732a21bf6c390e22578`.
- Origin: PR #393 merge.
- Candidate tree: `71bb8da37f55cc5b1bb4c8ed0f004f47a4ebf00e`.
- Architecture authority for the final two observation gaps: Amendment 0004,
  `docs/architecture/amendments/0004-derived-resource-public-read-boundary.md`.

PRs #394, #395 and #396 are reviewed evidence/governance descendants of that
fixed production candidate. The T24 candidate fence rejects production-changing
descendants before certification execution.

## Required inputs consumed

### T21 — governance/status reconciliation

T21 is complete: PR #385 merged as
`4b134f391c307915da28df5846108210467dd1e3`; CI run `33251875589` passed.
Its historical snapshot is retained as history and is not promoted into later
certification evidence.

### T22 — certification manifest

T22 is complete by PR #394, merge
`b225d9c36662432bc4f377d8d4f29d0f1ed763fa`.

The merged manifest represents exactly CV-001 through CV-040, is deterministic
and duplicate-free, records **40 ready / 0 capability gap**, and treats
CV-028/CV-029 as controlled-fixture scenarios whose acceptance observations use
the formal `LoomClient` read boundary.

### T23 — core integrated gate

T23 is complete from PR #394 / merge
`b225d9c36662432bc4f377d8d4f29d0f1ed763fa` / CI run `33288294125`.
Both required jobs passed, including dependency/security policy, architecture
checks, fmt/check/strict Clippy, full workspace tests, rustdoc and the complete
PostgreSQL 18 persistence contract. The fixed production candidate also has
exact-tree implementation CI from PR #393 run `33269628735`.

### T24 — trustworthy Validator certification gate

T24 is complete by PR #395, merge
`411e5bf7c573d39d1e6ec9fc7ddfed4a3f4d6901`, CI run `33290303853`.

Its canonical machine artifact (`validator-t24-final-certification`, artifact id
`9725902703`, digest
`sha256:2b15838ebd87ce5c69163c9d487d545f29a330108917898ef2f4462ea17b7788`)
records:

- candidate `02c55a6b5c34f227abfcb732a21bf6c390e22578`;
- merged T22 input `b225d9c36662432bc4f377d8d4f29d0f1ed763fa`;
- exactly 40 CV rows;
- **40 Pass / 0 Fail / 0 Unavailable**;
- `manifest_gap_count = 0`;
- all 17 command groups executed nonzero passing tests;
- `gate_passes = true`.

PR #396 independently re-ran the same strengthened CI on the published
certificate. Run `33290933514` again passed full workspace tests, T24 40-CV
certification, rustdoc and the complete PostgreSQL 18 job. Its T24 artifact is
id `9726075583`, digest
`sha256:c6271ca4640aa854f5c637530d2940c40bd771f625bc7d03b2aa5c66b2d2f834`.

## PostgreSQL 18 required-live evidence

Real PostgreSQL 18 evidence is present; no required-live row is certified from
skip, environment inference or an unavailable result. T20 remains the live
matrix authority for its frozen 10-row set, and PRs #394, #395 and #396 all
executed the repository PostgreSQL 18 contract successfully. T24 also invokes
the T20 live gate as one of its certification command groups.

## CV-028 / CV-029 closure

The historical final gaps were semantic-projection rebuild equivalence and
exact blob/reference integrity observation. T27 / PR #393 closed them under
Amendment 0004 with two narrow read-only Query operations. No public semantic
projection mutation/admin API and no public blob mutation/list/browse API was
added.

Fresh certification observes both capabilities through `LoomClient`;
controlled Runtime/ProjectionStore/BlobStore access is setup/fault-driver
support only. The `semantic_blob` suite executes the controlled InMemory and
PostgreSQL 18 evidence paths.

## Historical evidence boundary

Historical M13 and superseded Validator candidates remain historical facts and
are not rewritten by this certificate. In particular:

- M13 candidate/integration evidence remains historical;
- the pre-Amendment-0004 **38 Pass / 2 Unavailable** T24 result remains the
  truthful result for its old candidate;
- historical PR #380 / cancelled T26 are not current acceptance evidence;
- the current PASS derives from PR #393 implementation, PR #394 manifest/core
  evidence, PR #395 final 40-CV certification, and PR #396 durable certificate
  publication.

## Residual certification gaps

**None.**

T22 has no blocking capability gap, T24 reports all 40 CV rows as Pass, and no
required PostgreSQL row is skipped or unavailable. No unresolved P0/P1
Validator authority gap is hidden behind aggregate status.

## Tracker/root reconciliation

All executable recert leaves are complete. Stage 1 and Stage 2 have all child
leaves completed; Stage 3 has T21 through T25 completed. T27 is completed by
PR #393. The remaining work after this record is merged is only GitHub tracker
and root issue state reconciliation; no product or certification work remains.

## Root #302 closure checklist

- [x] Concrete production candidate SHA is fixed.
- [x] Integrated core evidence is green.
- [x] Validator evidence is trustworthy and reports 40/40 Pass.
- [x] Required PostgreSQL 18 evidence is real execution.
- [x] T22 has no unresolved certification gap.
- [x] Historical evidence remains historical rather than rewritten.
- [x] Full re-certification Task Ledger invariants are enforced in CI.
- [x] Certificate publication PR #396 merged with successful CI.
- [x] T25 completion metadata records PR #396 and merge SHA.

## T25 acceptance

- [x] T21, T23 and T24 contain completed durable evidence.
- [x] T22 has no unresolved blocking certification gap.
- [x] Core and Validator evidence certify the same fixed production candidate
  through explicitly reviewed evidence-only descendants.
- [x] PostgreSQL-required evidence is real PostgreSQL 18 execution.
- [x] Exact candidate, T22/T23/T24 evidence, CI run IDs and T24 artifact
  identities are recorded.
- [x] Residual gaps are truthfully `none` based on the 40-row T24 report.
- [x] Certificate publication PR, merge SHA and successful CI are recorded.
