---
task: VALR-T26
issue: ME-302
status: in_progress
depends_on: []
created_at: 2026-08-29
started_at: 2026-08-29
completed_at:
completion_pr:
merge_sha:
---

# VALR-T26 — Public semantic derived-read and blob/reference availability contract

This record covers the public read boundary required before the T15 CV-028/CV-029
re-audit. It does not change T15's result or ledger, the central Validator
registry (T19), or the certification manifest/gate (T22/T24).

## Contract

- `QueryService::query_semantic_projection` addresses an explicit World/Timeline,
  index identity, query/model revisions and either an exact committed source
  revision or the current committed revision. A successful
  `SemanticProjectionRead` returns the resolved source revision and projection
  identity with provider-neutral hits.
- Missing/rebuilding materialization is
  `semantic_projection_unavailable`; stale projection revisions are
  `semantic_projection_stale`; source metadata mismatch is
  `semantic_projection_source_mismatch`. None is an empty success or an
  inferred World read.
- `QueryService::read_blob` addresses one exact `BlobReference` and returns
  verified bytes plus the same stable reference metadata. Missing, integrity
  failure and adapter unavailability are respectively `blob_not_found`,
  `blob_integrity_mismatch` and `blob_unavailable`; no alternate reference or
  latest object is consulted.
- Runtime owns the mediation and retains the existing `BlobStore` behind its
  port. Boundary and Client expose only `loom-api` values and routes; no SQL,
  provider, object-store or storage-handle type crosses the public boundary.

## Implementation and evidence

- `crates/loom-api`: provider-neutral semantic/blob request and result models,
  typed error codes, and QueryService methods.
- `crates/loom-runtime`: Runtime-mediated semantic read with resolved source
  revision, exact blob verification through injected `BlobStore`, and typed
  error mapping.
- `crates/loom-boundary` and `crates/loom-client`: formal JSON routes and
  client adapters for both reads.
- `apps/loom-server`: production composition injects the existing local blob
  adapter into Runtime.
- `apps/loom-validator/tests/semantic_blob.rs`: controlled InMemory and
  PostgreSQL 18 fixtures now observe semantic rebuild/delete/recreate and blob
  missing/integrity behavior through the formal client surface while public
  History/Facet/Timeline reads remain unchanged.

## AC mapping

- Formal semantic read identity/revision and typed unavailable/stale/source
  outcomes → `loom-api` QueryService, Runtime mapping, boundary/client routes.
- Projection delete/rebuild equivalence and authoritative-history isolation →
  CV-028 fixture's formal reads and public History/Facet/Timeline assertions.
- Exact blob success/not-found/integrity distinction and no World mutation →
  CV-029 fixture's formal reads and public History/Facet assertions.
- Pinned/versioned behavior remains explicit → semantic query's
  `at_source_revision` and existing CV-030 path; no T15 result change.
- InMemory + controlled PostgreSQL 18 execution → 11-test semantic_blob suite.

## Verification evidence

Recorded against the candidate before review:

- `cargo check -p loom-api -p loom-runtime -p loom-boundary -p loom-client -p loom-server` → PASS.
- `cargo check -p loom-validator --test semantic_blob` → PASS.
- `env -u LOOM_TEST_POSTGRES_URL cargo test -p loom-validator --test semantic_blob -- --nocapture` → PASS; 11 passed, 0 failed, 0 ignored, 0 filtered out, including InMemory and repository-managed PostgreSQL 18 cases.
- `bash tools/validator-pg18-gate.sh` with a fresh PostgreSQL 18 control database → PASS; both gate tests passed and all 10 required live rows were `pass`, with trusted PostgreSQL evidence and controlled-boundary-restart evidence.
- `cargo fmt --all -- --check` → PASS.
- `cargo check --workspace --all-targets --all-features` → PASS.
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` → PASS.
- `python3 tools/test_validator_ready.py` and `python3 tools/validator_ready.py --check` → PASS; the latter reported the repository's existing planned/in-progress validator dependencies without a checker failure.
- `python3 tools/check_architecture.py`, `python3 tools/check_storage_sql_ownership.py`, `git diff --check`, and `cargo deny check advisories bans licenses sources` → PASS.
- `LOOM_TEST_POSTGRES_URL=<fresh PostgreSQL 18 control database> bash tools/test.sh --workspace --all-features` → PASS; all workspace targets, validator suites, semantic_blob (11 tests), PostgreSQL live gate (2 tests), and doc-tests passed with zero failures.

## Scope fence

No T15/T19/T22/T24 ledger, registry, result, manifest or gate file was edited.
The next action after this contract is merged is the separate T15 CV-028/CV-029
re-audit.
