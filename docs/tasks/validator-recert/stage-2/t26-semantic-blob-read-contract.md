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

### Historical AC mapping

- Formal semantic read identity/revision and typed unavailable/stale/source
  outcomes → `loom-api` QueryService, Runtime mapping, Boundary/Client routes.
- Projection delete/rebuild equivalence and authoritative-history isolation →
  CV-028 formal reads and public History/Facet/Timeline assertions.
- Exact blob success/not-found/integrity distinction and no World mutation →
  CV-029 formal reads and public History/Facet assertions.
- Pinned/versioned behavior remained explicit → semantic query's
  `at_source_revision` and the existing CV-030 path; no T15 result change.
- InMemory + controlled PostgreSQL 18 execution → the 11-test semantic_blob
  suite.

### Historical verification evidence

The following evidence was recorded against the PR #380 candidate before
review. It remains historical and does not certify the reverted implementation:

- `cargo check -p loom-api -p loom-runtime -p loom-boundary -p loom-client -p loom-server` → PASS.
- `cargo check -p loom-validator --test semantic_blob` → PASS.
- `env -u LOOM_TEST_POSTGRES_URL cargo test -p loom-validator --test semantic_blob -- --nocapture` → PASS; 11 passed, 0 failed, 0 ignored, 0 filtered out.
- `bash tools/validator-pg18-gate.sh` with a fresh PostgreSQL 18 control database → PASS; 10 required live rows passed.
- `cargo fmt --all -- --check`, workspace check, strict clippy, architecture
  check, storage SQL ownership, `git diff --check`, and cargo-deny checks →
  PASS.
- Validator readiness checks and the full workspace test wrapper were recorded
  as PASS for that candidate.

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
