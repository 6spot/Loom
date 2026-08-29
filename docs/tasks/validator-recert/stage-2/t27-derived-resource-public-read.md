---
task: VALR-T27
issue: 392
status: in_progress
depends_on: []
created_at: 2026-08-30
started_at: 2026-08-30
completed_at:
completion_pr:
merge_sha:
---

# VALR-T27 — Formal derived-resource public read boundary (CV-028/CV-029)

## Purpose

This is a fresh current-main remediation leaf for the two remaining formal-observation gaps discovered during Validator re-certification. It does not inherit a Pass result from earlier agents, T15/T22/T24 ledgers, or historical PR #380. Those records are reference material only until the exact implementation candidate is independently verified.

The architectural authority for this work is [`../../../architecture/amendments/0004-derived-resource-public-read-boundary.md`](../../../architecture/amendments/0004-derived-resource-public-read-boundary.md).

## Current-main finding

The repository already contains the underlying M7 capabilities:

- Runtime-owned semantic projection/retrieval with revision identity and typed derived-state failure semantics;
- immutable content-addressed blob storage behind the Runtime/Storage boundary.

The missing capability is the sanctioned consumer observation path. Current `loom-api::QueryService` exposes the v0 Facet read slice but no provider-neutral semantic projection read and no exact blob-reference fetch. Using Runtime internals, projection stores, BlobStore handles or SQL as Validator evidence would violate the existing public-boundary architecture.

Therefore this leaf implements only the two narrow read operations authorized by Amendment 0004.

## Allowed implementation scope

- `crates/loom-api` — provider/storage-neutral request/result/error vocabulary and `QueryService` methods.
- `crates/loom-runtime` — Runtime-mediated semantic/blob read orchestration and typed error mapping.
- `crates/loom-boundary` — HTTP transport for the formal operations.
- `crates/loom-client` — ordinary external consumer adapters.
- `apps/loom-server` — composition wiring only.
- `apps/loom-validator/tests/semantic_blob.rs` and minimal owning Validator code needed to replace blocked observation assertions with formal `LoomClient` evidence.
- focused architecture/task/certification/CI records required to verify this candidate.

## Forbidden scope

- no public semantic projection register/rebuild/delete/write/admin operation;
- no public blob write/delete/list/browse operation;
- no direct Validator Storage/SQL/BlobStore acceptance observation;
- no provider-specific semantic SDK/model/storage types in `loom-api`;
- no new World authority, Event/Effect/Work/TimelineVersion mutation semantics;
- no central registry placeholder or fake `Pass` for CV-028/CV-029;
- no resurrection of cancelled VALR-T26 as a current task or evidence source.

## Evidence contract

### CV-028 — Semantic projection rebuild equivalence

A controlled test-only driver may create, remove and rebuild the derived projection. The acceptance observations must come through formal public reads:

1. `LoomClient` semantic projection query returns the expected provider-neutral result and exact resolved source/projection identity.
2. Removing the derived projection produces the typed public unavailable result.
3. Public History/Facet observations remain unchanged while derived state is absent.
4. Rebuilding the projection produces an equivalent public semantic result for the same committed World truth.
5. Stale projection and source-revision mismatch paths fail closed with distinct typed outcomes.

### CV-029 — Blob/reference integrity

A controlled test-only driver may prepare present, missing and corrupt backing bytes. Acceptance observations must come through formal public reads:

1. `LoomClient` exact blob-reference fetch returns verified bytes and stable reference metadata.
2. Missing backing data produces a typed not-found outcome.
3. Corrupt backing data produces a typed integrity-mismatch outcome.
4. Backing-adapter unavailability remains distinct from not-found/integrity failures.
5. Public History/Facet observations remain unchanged across all derived-resource failures.

## Validation plan

The exact candidate must pass, without reusing previous Pass claims:

- focused API / Runtime / Boundary / Client tests;
- controlled InMemory semantic/blob validation;
- controlled PostgreSQL 18 semantic/blob validation where applicable;
- `cargo fmt --all -- --check`;
- `cargo check --workspace --all-targets --all-features`;
- `cargo clippy --workspace --all-targets --all-features -- -D warnings`;
- `bash tools/test.sh --workspace --all-features`;
- `RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps`;
- `cargo deny check advisories bans licenses sources`;
- `python3 tools/check_architecture.py`;
- `python3 tools/check_storage_sql_ownership.py`;
- fresh current-candidate Validator certification gate.

## Acceptance

- [ ] Amendment 0004 is indexed before implementation.
- [ ] Product API growth is limited to the two read-only operations.
- [ ] Runtime remains the sole gateway behind both reads.
- [ ] CV-028 observations use `LoomClient` and prove unchanged World truth across delete/rebuild.
- [ ] CV-029 observations use `LoomClient` and distinguish success/not-found/integrity/unavailable while World truth remains unchanged.
- [ ] No projection/blob mutation authority is public.
- [ ] Exact-candidate full CI is green.
- [ ] Completion fields are populated only after the implementation PR merges and its exact evidence is known.

## Progress log

- 2026-08-30 — Independently re-audited current main rather than trusting historical task status. Confirmed that M7 semantic/blob capabilities exist below the public boundary, T08 authorizes test-only setup but requires formal LoomClient observations, and the minimal missing product capability is exactly two read-only Query operations. Amendment 0004 was created and registered before implementation; this fresh leaf records the implementation boundary.
