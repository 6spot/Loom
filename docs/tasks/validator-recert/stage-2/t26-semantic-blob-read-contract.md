---
task: VALR-T26
issue: ME-302
status: cancelled
depends_on: []
created_at: 2026-08-29
started_at: 2026-08-29
completed_at:
completion_pr:
merge_sha:
---

# VALR-T26 — Public semantic derived-read and blob/reference availability contract

This record is retained as an audit history for the public-read implementation
that was merged by PR #380 and subsequently reverted by ME-303. The contract
below is historical evidence only; it is not a current production capability,
Validator Pass, or accepted architecture amendment.

## Historical contract (implemented in PR #380; not current)

- `QueryService::query_semantic_projection` addressed an explicit World/Timeline,
  index identity, query/model revisions and either an exact committed source
  revision or the current committed revision. A successful
  `SemanticProjectionRead` returned the resolved source revision and projection
  identity with provider-neutral hits.
- Missing/rebuilding materialization mapped to
  `semantic_projection_unavailable`; stale projection revisions mapped to
  `semantic_projection_stale`; source metadata mismatch mapped to
  `semantic_projection_source_mismatch`.
- `QueryService::read_blob` addressed one exact `BlobReference` and returned
  verified bytes plus stable reference metadata. Missing, integrity failure and
  adapter unavailability mapped to `blob_not_found`,
  `blob_integrity_mismatch` and `blob_unavailable`.
- Runtime mediated these reads behind the existing `BlobStore` port, while
  Boundary and Client exposed `loom-api` values and routes.

## Historical implementation and evidence

PR #380 (merge commit
`ef281f886480663a94193f738179d14933040a12`, head
`3abc7f65d21fe7d6564c671ab18db11420da3741`) changed the following paths:

- `crates/loom-api`, `crates/loom-runtime`, `crates/loom-boundary`, and
  `crates/loom-client`;
- `apps/loom-server`, `apps/loom-cli`, and
  `apps/loom-validator/tests/semantic_blob.rs`.

The PR's recorded candidate checks and semantic_blob evidence remain historical
facts about that merged candidate, not evidence for the reverted code. The
implementation was not accepted as a current architecture/remediation because
the required Architecture Amendment was absent.

## Cancellation and rollback log

- 2026-08-29 — PR #380 merged the implementation described above.
- 2026-08-29 — ME-303 reverted merge commit
  `ef281f886480663a94193f738179d14933040a12` with ordinary revert commit
  `33a916e02d5a458261b6eaf63e5bf510f1758af5`. The revert restores the pre-#380 public API boundary while
  preserving the #380 merge and this audit record.
- 2026-08-29 — T26 is marked `cancelled`; no current semantic/blob public
  capability or Validator certification is claimed. Any future public-read
  work requires the Architecture Amendment gate and a separately scoped task.

## Scope fence

No T15/T19/T22/T24 ledger, registry, result, manifest or gate file was edited
by PR #380 or this rollback. T15 CV-028/CV-029 remain the documented gaps;
this retained record does not convert either gap to Pass.
