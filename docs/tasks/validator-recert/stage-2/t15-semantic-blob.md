---
task: VALR-T15
issue: 320
status: completed
depends_on: [314]
created_at: 2026-08-26
started_at: 2026-08-27
completed_at: 2026-08-28
completion_pr: 374
merge_sha: bed2dac9947d5c5f92e0d530378f5be712e041a6
---

# VALR-T15 — Validate Semantic projection + Blob references + pinned reads

T15 owns `CV-028..CV-030`. `CV-028`/`CV-029` are explicit formal-read gaps per `t08-coverage-matrix.md`: `no existing formal semantic projection observable` and `no existing formal blob/reference fetch observable`. These are not product API or Architecture Amendment authorization; controlled Runtime/Storage fixtures are test-only drivers, and the formal result remains `Unavailable`. `CV-030` is the sole implementable candidate via existing `ForkTimelineRequest::at_version` + `QueryService::get_facet`/`HistoryService::list_events`/`TimelineService::inspect_timeline`. This leaf implements `CV-030` pinned-version stability via real `create-world`/`seed`/`increment`/`fork at_version` and records the CV-028/CV-029 gaps without inventing authority, storage inspection, or `Pass`.

## Goal

Validate that semantic projections and blob-backed/pinned reads behave as derived/public read capabilities without becoming alternate World authority, per `t08-coverage-matrix.md` detailed specs `CV-028..CV-030` and this leaf's Stop Conditions.

## Scope

Allowed (per Leader call):

- `apps/loom-validator/src/semantic_blob.rs` — descriptors, `register`, `execute`, `blocked_descriptors` for `CV-028..CV-030`; `CV-030` via public `loom-api`/`loom-client` only.
- `apps/loom-validator/tests/semantic_blob.rs` — real public-HTTP integration tests with `tests/common` harness (`InMemory` + live `PostgreSQL`), unique IDs, no direct SQL/storage/table assertions.
- This ledger `t15-semantic-blob.md`.

Forbidden:

- No `apps/loom-validator/src/lib.rs`, central `validator_registry`/`registry.rs`, `tests/common/mod.rs`, other `src/*.rs`/`tests/*.rs`, `loom-api`/`loom-client`/`loom-runtime`/`loom-storage`/`loom-boundary`, or `t09-suite-scaffold.md` edits.
- No Central registry enlargement (`T19` owns `CV-012..040` integration); blocked gaps must not be registered.
- No `loom-api` invention: `CV-028`/`CV-029` have no public semantic rebuild/query or blob fetch surface; do not enter internal runtime/storage tables or forge `Pass`.

## Coverage Matrix Mapping

| CV | Capability / Clause | Formal Public Surface | Expected Observable Result | Evidence Class | PG live? | Owner | Status in this leaf |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CV-028 | Semantic projection rebuildable, not authority (`m7/t2-t3`) | No existing formal semantic projection observable; only `CatalogService::catalog#SemanticIndexDescriptor` metadata plus authoritative `HistoryService::list_events`/`QueryService::get_facet` reads | Blocked: the controlled driver may build/delete/rebuild, but Validator cannot formally observe that projection operation; this is a formal-read gap, not a product API / Architecture Amendment request | blocked (`no existing formal semantic projection observable`) | No — blocked | T15 (#320) | Blocked gap: `Unavailable` with `finding:gap:CV-028-no-public-semantic-projection-api`; not registered; documented here |
| CV-029 | Blob/reference missing does not rewrite history (`m7/t4`) | No existing formal blob/reference fetch observable; only authoritative `QueryService::get_facet` + `HistoryService::list_events`, with opaque `FacetSnapshot.value` | Blocked: the controlled driver may make a reference unavailable, but Validator cannot formally observe the fetch failure; this is a formal-read gap, not a product API / Architecture Amendment request | blocked (`no existing formal blob/reference fetch observable`) | No — blocked | T15 | Blocked gap: `Unavailable` with `finding:gap:CV-029-no-public-blob-service-api`; not registered |
| CV-030 | Pinned/versioned read via `fork at_version` (`m7/t5`, amendment 0003 §4) | `TimelineService::fork(ForkTimelineRequest::at_version(source, TimelineVersion))` then `QueryService::get_facet` + `HistoryService::list_events` + `TimelineService::inspect_timeline` for `ancestry.fork_parent_version`/`fork_parent_event` | Fork `get_facet` returns pinned value `10` even though head is `11`; `fork_parent_version == Some(pinned)` and `fork_parent_event == Some(pinned EventRef)`; `list_events(fork)` contains pinned history only (1 event) with `EventSeq` ordering; source remains `11` after fork | controlled `InMemory`, controlled `PostgreSQL` | Yes | T15 | Implementable: `Pass` via real public HTTP client; T19 candidate |

Details per T08: `CV-028`/`CV-029` gaps are `Coverage Gaps 8/9`; `CV-030` is the corrected existing API path (no invented `get_facet_at_version`/`BaseWorldView`).

## CV-030 Production Scenario (public `loom-api`/`loom-client` only)

- **Preconditions:** fresh `World` via `WorldService::create_world_from_template` (`validator.t15.<scope>` revision 1, `WorldInstant(42)`, `requires_capability("neutral.counter","^0.1.0")`); fresh `EntityId`.
- **Steps using actual `TimelineVersion`:**
  1. `ActionService::invoke` `neutral.counter.seed` with `value=10` → `ExecutionResult::Committed { timeline_version: version_a }`. Record `version_a` (actual returned, e.g. `head_event_seq=1, state_revision=1`).
  2. `QueryService::get_facet(FacetQuery::new(target, entity, "neutral.counter.value"))` → `10`; `HistoryService::list_events` → `len 1` with `pinned_event_id`.
  3. `ActionService::invoke` `neutral.counter.increment` with `amount=1` → `version_b` where `version_b != version_a` and `head_event_seq` advanced by 1.
  4. Verify source `get_facet` → `11` and `list_events` → `len 2` with `EventSeq` ordering.
  5. `TimelineService::fork(ForkTimelineRequest::at_version(source, version_a))` → `child_snapshot`/`child_target`.
  6. Verify via `inspect_timeline`: `ancestry.fork_parent_version == Some(version_a)`, `parent_timeline_id == Some(source)`, `fork_parent_event == Some(EventRef(source, pinned_event_id))`; `version` equals `version_a` (pinned).
  7. Re-`inspect_timeline(child_target)` and `get_facet(child_target)` → `10` (pinned, not `11`); `list_events(child_target)` → `len 1` with `id == pinned_event_id` and `sequence == history_a[0].sequence`.
  8. Re-verify source after fork still `11` and `inspect_timeline(source).version == version_b`; history pinned vs head isolated.
- **Not asserted:** projection or blob storage is World authority. Scenario never asserts via `loom-storage`/`loom-runtime` tables, `SemanticIndexDescriptor` beyond catalog metadata, or invented `get_facet_at_version`.

Evidences: `public-surface:loom-client::WorldService::create_world_from_template`, `ActionService::invoke#seed+increment`, `QueryService::get_facet#pinned+head+fork`, `HistoryService::list_events#pinned+head+fork`, `TimelineService::fork#at_version`, `TimelineService::inspect_timeline#fork+source`; `validator:scenario:CV-030#pinned-stability`; `t09-fence:preserved-no-lib-registry-edit`.

## T09 Dependency Fence and T19 Surface

- **Fence:** No `src/lib.rs`/`registry.rs` edits; on current main the central `validator_registry()` contains the 32 implementable scenarios and still excludes blocked CV-028/CV-029. Suite exposes isolated `ScenarioRegistry` via `semantic_blob::register(&mut isolated)` adding only `CV-030` (tested to be `1`); no `CV-012..040` placeholder `Pass` is introduced in `src/`/`tests/`.
- **T19 surface:** `semantic_blob::descriptors() -> Vec<ScenarioDescriptor>` (len `1`, `CV-030` only), `blocked_descriptors() -> Vec<ScenarioDescriptor>` (len `2`, `CV-028`/`CV-029` gap metadata), `register(registry) -> Result<usize, RegistryError>` (registers only `CV-030`), `execute(descriptor, ctx) -> ScenarioResult` (handles `CV-030` `Pass`/`Fail` and blocked `Unavailable` with gap evidence), `owns_cv`, `suite_name`, `SUITE`, `CV_RANGE`, `CAPABILITY_AREA`. Central registry enlargement stays in `T19`; blocked items never become `Pass`.

## AC → Implementation Mapping

- **AC-1 CV-028..CV-030 match T08:** `CV-028`/`CV-029` recorded as blocked gaps per T08 `blocked (no public surface)` with `Unavailable` and `finding:gap:...` evidence; `CV-030` matches T08 `ForkTimelineRequest::at_version` + `get_facet`/`list_events`/`inspect_timeline` with version stability, ancestry, and history checks. Sources: `src/semantic_blob.rs:descriptors`, `blocked_descriptors`, `execute::cv028_blocked`, `cv029_blocked`, `cv030`; `t08-coverage-matrix.md#CV-030`.
- **AC-2 Projection never asserted as authoritative World state:** Production `cv030` never renders `projection is World authority`; finding `actual`/`expected` describe pinned `get_facet`/`list_events`/`inspect_timeline` only; `catalog#SemanticIndexDescriptor` is read-only metadata (gap). Tests assert no `projection is world authority` and no `loom_storage`/`pgstorage`/`sqlx` in evidence. Sources: `src/semantic_blob.rs:cv030` expected/actual, `tests/semantic_blob.rs:cv030_*` assertions.
- **AC-3 Blob unavailability cannot mutate or reinterpret history:** `CV-029` blocked; `CV-030` does not use blob surfaces and verifies history isolation (`child len 1` vs `head len 2`, `EventSeq` ordering) remains unchanged despite fork; blocked `cv029_blocked` cites `Catalog`/`get_facet` opaque only. Sources: `src/semantic_blob.rs:cv029_blocked`, `cv030` history checks.
- **AC-4 Pinned reads demonstrate version stability:** Source `10@version_a` → `11@version_b` via actual returned `TimelineVersion`; fork at `version_a` reads `10` while source is `11`; `ancestry.fork_parent_version == Some(version_a)` and `fork_parent_event == Some(pinned EventRef)`; `list_events(fork)` pinned `1` vs `2`; source stable after fork. Tests assert same via real services on `InMemory` and `PostgreSQL` live. Sources: `src/semantic_blob.rs:cv030` steps 6-12; `tests/semantic_blob.rs:cv030_pinned_read_*`.
- **AC-5 Dedicated tests + fmt/check/clippy + CI pass; review complete:** `tests/semantic_blob.rs` covers `InMemory` + live `PostgreSQL` with unique IDs via `tests/common` harness and real public HTTP client; `cargo fmt --check`, `cargo check -p loom-validator --all-targets`, `cargo clippy -D warnings`, `cargo test -p loom-validator --all-targets`, `cargo test -p loom-validator --test semantic_blob`, `validator_ready --check`, `check_architecture`, `check_storage_sql_ownership`, `git diff --check` verified (see Verification Evidence).

## Blocked Gaps Detail (must not be registered)

- **CV-028:** No existing formal semantic projection observable: `crates/loom-api`/`loom-client` expose only `SemanticIndexDescriptor` metadata via `CatalogService::catalog` and authoritative `HistoryService`/`QueryService` reads. The controlled driver cannot turn those reads into projection evidence; do not invent an alternative via internal `loom-storage` tables. Evidence `finding:gap:CV-028-no-public-semantic-projection-api`; `semantic_blob::execute` returns `Unavailable`, `descriptors()` excludes it, and `blocked_descriptors()` documents it.
- **CV-029:** No existing formal blob/reference fetch observable: `FacetSnapshot.value` may contain opaque `BlobReference`, but public `get_facet`/`list_events` cannot observe fetch failure. Internal BlobStore/SQL cannot substitute. Evidence `finding:gap:CV-029-no-public-blob-service-api`; `semantic_blob::execute` returns `Unavailable`, `descriptors()` excludes it, and `blocked_descriptors()` documents it.

Both gaps remain formal-read gaps; this leaf does not request or authorize a product API or Architecture Amendment, and does not add API, storage table inspection, or fake `Pass`.

## Integration Tests (real public HTTP, no storage SQL)

Harness: `apps/loom-validator/tests/common/mod.rs` (`InMemoryServer::start`, `PgServer::start`, `PgStorage`/`InMemoryStore` + `Runtime` + `loom-boundary::router_with_admin` over HTTP, `LoomClient` via `BackendContext::new(client).with_backend_kind(...).with_scope(...)`).

- `semantic_blob_suite_scaffold_is_non_registering_and_disjoint` — `SUITE`/`CV_RANGE`/`owns_cv`, current-main `validator_registry len 32`, no blocked CV-028/CV-029 registered, isolated `register` adds only `CV-030`.
- `semantic_blob_descriptors_are_stable_and_not_centrally_registered` — `descriptors len 1 == CV-030`, `blocked len 2`, none centrally registered.
- `cv030_pinned_read_pass_on_real_in_memory` — InMemory live service: `execute CV-030` should `Pass`; evidences contain `public-surface:loom-client::WorldService::create_world_from_template`, `ActionService`, `QueryService`, `HistoryService`, `TimelineService::fork#at_version`/`inspect_timeline`; no `loom_storage`/`pgstorage`/`sqlx`/`semantic_projection`/`blobstore`; actual contains `pinned`, `fork_parent_version`, `ancestry`; source stability verified; unique scope.
- `cv030_pinned_read_pass_on_live_postgres` — PostgreSQL live: same checks with `backend postgresql` evidence; T08 requires PG and not skipped; uses `PgServer::start` (starts `compose.test-db.yaml` if needed) via `LoomClient`; no `skip` bypass.
- `cv028_and_cv029_are_blocked_gaps_on_in_memory_and_pg` — `CV-028`/`CV-029` on both backends return `Unavailable` with `gap` evidence and never `Pass`.
- `cv028_cv029_do_not_enlarge_central_registry_even_when_executed` — executing blocked scenarios does not enlarge current-main `validator_registry` (`len 32`) and leaves CV-028/CV-029 absent.
- `semantic_blob_register_fence_preserves_only_cv030` — `register(&mut isolated)` adds `1` (`CV-030` only), while current-main central remains `32` and excludes CV-028/CV-029.

Unique ID: `unique_scope` with `Uuid::new_v4()` per test (e.g. `cv030-inmem-<uuid>-t15`); prohibits direct SQL/storage/table assertion (only `get_facet`/`list_events`/`inspect_timeline`/`fork`).

## Historical Verification Evidence — initial implementation candidate (superseded)

- `cargo fmt --all -- --check` → `0` (via `cargo fmt --all` applied)
- `cargo check -p loom-validator --all-targets` → pass (no `lib.rs` registry edit, `semantic_blob` compiles with `loom-api` only)
- `cargo clippy -p loom-validator --all-targets -- -D warnings` → pass (pedantic allows)
- `cargo test -p loom-validator --all-targets` → `semantic_blob` InMemory `Pass`, PG live `Pass` when `LOOM_TEST_POSTGRES_URL`/compose DB available; blocked gaps `Unavailable`; no filtered/ignored placeholder; `validator_registry len 11` preserved
- `cargo test -p loom-validator --test semantic_blob` → same as above (7 tests)
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json` → `valid` reflects T09 fence: `VALR-T15` `depends_on [314]` (`VALR-T09` `in_progress`) is recorded; `T09` scoop still `in_progress` per `da18e40` baseline, so `T15` remains `in_progress` blocked until `T09` completion — `valid` would be `false` while dependency is `in_progress`, but `record_count` and `t15-semantic-blob.md` metadata are correct and `T09` file is not modified per fence (see Progress Log)
- `python3 tools/check_architecture.py` → `Loom architecture dependency policy: OK`
- `python3 tools/check_storage_sql_ownership.py` → `storage SQL ownership check passed`
- `git diff --check` → no whitespace errors

## Acceptance

- [x] `CV-028..CV-030` match `t08-coverage-matrix.md` detailed specs (see Coverage Matrix Mapping and AC Mapping)
- [x] Projection is never asserted as authoritative World state (see `cv030` and test assertions)
- [x] Blob unavailability cannot mutate or reinterpret history (blocked `CV-029` and pinned history isolation)
- [x] Pinned reads demonstrate version stability via actual `TimelineVersion` (see `CV-030 Production Scenario` steps 6-12 and InMemory+PG tests)
- [x] Dedicated tests + `fmt`/`check`/`clippy` + CI pass; ledger records `status`/`depends_on [314]`/gap basis/`CV-030` evidence/AC mapping and verification results; `T09` record not modified

## Stop Conditions

If existing public `loom-api` cannot express required pinned/semantic read without new semantic decision, stop and record gap rather than reaching into internal storage — implemented: `CV-028`/`CV-029` are recorded as `Unavailable` gaps with `no existing formal semantic projection observable` / `no existing formal blob/reference fetch observable`; this is not product API or Architecture Amendment authorization. `CV-030` uses existing `ForkTimelineRequest::at_version` path and does not invent `get_facet_at_version`/`BaseWorldView`.

## Historical Progress Log — append-only

- 2026-08-27 — Implemented `CV-030` via public `loom-api`/`loom-client` (`create_world`, `seed` value `10` → `version_a`, `increment` to `11` → `version_b`, `fork at_version version_a`, `get_facet`/`list_events`/`inspect_timeline` for `fork_parent_version`/`fork_parent_event`/pinned history vs head). Kept `CV-028`/`CV-029` as `Unavailable` blocked gaps (`finding:gap:...`) without new API or storage inspection and without central registry enlargement (T09 fence: `validator_registry len 11`, `register` adds only `CV-030` for T19). Added `tests/semantic_blob.rs` real public-HTTP integration tests for `InMemory` and live `PostgreSQL` (T08 PG required, not skipped) with unique IDs and no SQL/table assertions. Preserved `SUITE`/`CV_RANGE`/`owns_cv` and exposed `descriptors`/`blocked_descriptors`/`register`/`execute` surface for T19. Verified `fmt`/`check`/`clippy`/`test` and architecture/storage checks with `git diff --check` clean.
- 2026-08-27 — Rework for D-001/D-002/D-003: restricted PostgreSQL live endpoint validation to implementable `CV-030`, so `CV-028`/`CV-029` always dispatch directly to `Unavailable` with `finding:gap` regardless of backend URL environment; removed the obsolete env-presence prerequisite gate because the repository harness uses its default control database when unset. Bound both returned `TimelineVersion` fields to public history `EventSeq` and `StateRevision` progression, strictly matched fork inspect version and complete source `EventRef` ancestry, and added controlled PostgreSQL boundary restart/reconnect reads for source/fork facet, history, inspect, pinned value, EventSeq and ancestry. The PG integration test now injects `PgServer::restart` through `BackendContext::restart`; T09 registry and other ledgers remain untouched.

## Rework Verification Evidence

- `env -u LOOM_TEST_POSTGRES_URL cargo test -p loom-validator --test semantic_blob -- --nocapture` → 7 passed; CV-028/CV-029 remained `Unavailable` gap results and CV-030 ran through the repository-default PostgreSQL harness.
- `LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_control cargo test -p loom-validator --test semantic_blob -- --nocapture` → 7 passed; CV-030 controlled PostgreSQL restart/reconnect evidence passed.
- `LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_control cargo test -p loom-validator --all-targets` → all targets passed, including 154 unit tests and all live integration suites.
- `cargo fmt --all -- --check`, `cargo check -p loom-validator --all-targets`, `cargo clippy -p loom-validator --all-targets -- -D warnings`, `python3 tools/check_architecture.py`, `python3 tools/check_storage_sql_ownership.py`, and `git diff --check` → passed.

## Remediation Audit — CV-028/CV-029 (2026-08-28)

This append-only record applies the T08 correction audit from the current
baseline `95f7e7a0233cfa917d0c9656b990fd2af4996874`: a test-only
Runtime/Storage driver is permitted, while acceptance authority remains the
formal `LoomClient` History/Facet/Timeline read surface. The previous
pre-policy blocked wording above is retained as historical evidence.

- `CV-028` → `apps/loom-validator/tests/semantic_blob.rs` now composes a real
  Runtime over `InMemoryStore` and `PgStorage`. It drives the existing
  Runtime-owned `SemanticProjectionStore` through `register`, `query`,
  `rebuild`, `delete`, re-register and rebuild. Public `HistoryService`,
  `QueryService` Facet, and `TimelineService` reads before/after deletion and
  rebuild remain byte-for-byte/equivalent in their authoritative Event/Facet
  values and Timeline version/time; projection hits are auxiliary evidence.
- `CV-029` → the same controlled public HTTP composition uses the concrete
  `InMemoryBlobStore` to produce a `BlobRef`, verifies a successful read, then
  simulates missing (`BlobError::NotFound`) and corrupt (`BlobError::HashMismatch`)
  bodies. Public `QueryService` Blob Facet and `HistoryService` reads remain
  unchanged after both typed adapter errors. No BlobService, semantic
  authority, SQL/table read, or production contract was added.
- Controlled evidence is present for both InMemory and real PostgreSQL 18
  Runtime/Storage backends. PostgreSQL is not a mandatory durability class for
  CV-028/CV-029 under the corrected T08 policy, but the PG18 path is executed
  and recorded here for backend parity. CV-030's existing pinned-read path is
  unchanged.

### Remediation verification

- `env -u LOOM_TEST_POSTGRES_URL cargo test -p loom-validator --test semantic_blob -- --nocapture` → PASS, 11 tests, including InMemory and repository-default PG18 CV-028/CV-029 fixtures and existing CV-030 coverage.
- `LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_control cargo test -p loom-validator --test semantic_blob -- --nocapture` → PASS, 11 tests, including explicit PG18 CV-028/CV-029 fixtures and existing CV-030 coverage.
- `LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_control cargo test -p loom-validator --all-targets` → FAIL in unrelated `authority_gate` report-writing cases because the shared filesystem reached `No space left on device`; the T15 semantic/blob tests had not failed. The executor-local `target/` was then cleaned and the targeted evidence above was rerun on the candidate.

## D-004 Rebase Verification — 2026-08-28

The candidate was rebuilt from the fetched `origin/main` at
`78781ba55f6fa5c21c377ff1d356be03a1742e72`; the prior exact-head evidence was
not reused. The rebased candidate before this append was
`5f5cf1ec61ee1a33792d228d6bc45bf2f7f55af8`; the final documentation-only
follow-up commit contains the same test implementation and records the final
HEAD in the delivery comment.

- Default repository PG18: `env -u LOOM_TEST_POSTGRES_URL cargo test -p loom-validator --test semantic_blob -- --nocapture` → 11 passed, 0 failed, 0 ignored, 0 filtered out.
- Explicit PG18: `LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_control cargo test -p loom-validator --test semantic_blob -- --nocapture` → 11 passed, 0 failed, 0 ignored, 0 filtered out.
- `cargo fmt --all -- --check`, `cargo check -p loom-validator --all-targets`, `cargo clippy -p loom-validator --all-targets -- -D warnings`, `python3 tools/check_architecture.py`, `python3 tools/check_storage_sql_ownership.py`, and `git diff --check origin/main..HEAD` → passed on the rebased candidate.

## D-004 Final Candidate Verification — 2026-08-28

The PG fixture setup now holds a test-only revision-state guard across each
fixture's lifetime, including the existing CV-030 PostgreSQL case. This keeps
parallel test setup from racing on the shared controlled database revision
generation; it does not add a production race protocol or alter business
semantics. Final candidate is based on
`78781ba55f6fa5c21c377ff1d356be03a1742e72`; final HEAD is recorded in the
Executor handoff comment.

- Default repository PG18 and explicit PG18 T15 suites each ran 11 tests with 11 passed, 0 failed, 0 ignored, 0 filtered out on the final implementation.
- `cargo fmt --all -- --check`, `cargo check -p loom-validator --all-targets`, `cargo clippy -p loom-validator --all-targets -- -D warnings`, `python3 tools/check_architecture.py`, `python3 tools/check_storage_sql_ownership.py`, and `git diff --check origin/main..HEAD` all passed on the final implementation.

## D-004 Latest-main Rebase — 2026-08-28

After the prior verification, `origin/main` advanced again. The candidate was
rebased from the freshly fetched base
`2c4bc4be8c2401c6b22598760aa99ff8a970300c`; the previous exact-head evidence
was invalidated and the T15 suite was rerun on the rebased candidate. The
final HEAD is recorded in the Executor handoff comment.

- Default repository PG18 and explicit PG18: each T15 `semantic_blob` run executed 11 tests with 11 passed, 0 failed, 0 ignored, 0 filtered out.
- fmt, check, clippy, architecture, storage ownership, and diff check all passed on this latest-main candidate.

## D-005 Latest-main Rebase — 2026-08-28

The T08 correction merge advanced `origin/main` after the prior D-004
verification. The candidate was rebuilt from freshly fetched
`c4e0ca14cf8746a6e43b5e87639a93cf321e3e1c` (which includes the T08 correction
merge); all prior exact-head evidence was treated as stale. The final HEAD is
recorded in the Executor handoff comment.

- Default repository PG18 and explicit PG18: each T15 `semantic_blob` run executed 11 tests with 11 passed, 0 failed, 0 ignored, 0 filtered out.
- `cargo fmt --all -- --check`, `cargo check -p loom-validator --all-targets`, `cargo clippy -p loom-validator --all-targets -- -D warnings`, `python3 tools/check_architecture.py`, `python3 tools/check_storage_sql_ownership.py`, and `git diff --check origin/main..HEAD` all passed on the rebased candidate.

## D-005 Final Latest-main Rebase — 2026-08-28

The candidate was rebased once more after the latest-main ledger merge. The
freshly fetched base is
`8031d1df0a6512a651979c60e2e8e7ef31f08139`; the final candidate HEAD is
recorded in the Executor handoff comment. The prior exact-head evidence was
not reused.

- Default repository PG18 and explicit PG18: each T15 `semantic_blob` run executed 11 tests with 11 passed, 0 failed, 0 ignored, 0 filtered out.
- `cargo fmt --all -- --check`, `cargo check -p loom-validator --all-targets`, `cargo clippy -p loom-validator --all-targets -- -D warnings`, `python3 tools/check_architecture.py`, `python3 tools/check_storage_sql_ownership.py`, and `git diff --check origin/main..HEAD` all passed on this candidate.

## Current-main Reconciliation — 2026-08-29

This append-only reconciliation is bound to current main base
`a898e5be6e33f5f448992c7ddb642af7336bc8f8`. It does not alter the historical
implementation, remediation, rebase, or verification records above.

### Effective disposition

- `CV-028` remains `Unavailable` with
  `finding:gap:CV-028-no-public-semantic-projection-api`. The controlled
  Runtime/Storage projection fixture is a test-only driver. InMemory and
  PostgreSQL 18 controlled runs show stable authoritative public
  `HistoryService`/`QueryService` Facet/`TimelineService` observations before
  and after the derived projection operations, but no existing formal semantic
  projection observable exists. `semantic_blob::descriptors()` intentionally
  contains only `CV-030`; CV-028 is exposed only through blocked metadata and
  is not registered.
- `CV-029` remains `Unavailable` with
  `finding:gap:CV-029-no-public-blob-service-api`. The controlled
  Runtime/Storage/BlobStore fixture is a test-only driver. InMemory and
  PostgreSQL 18 controlled runs show stable authoritative public Facet/History
  observations after typed missing/corrupt adapter failures, but no existing
  formal blob/reference fetch observable exists. `FacetSnapshot.value` remains
  opaque; internal BlobStore/SQL is not formal evidence, and CV-029 is not
  registered.
- The current effective T08 accounting remains **38 suitable / 2 blocked** for
  `CV-001..CV-040`; the two blocked rows are exactly CV-028 and CV-029. The
  controlled evidence does not convert either row to `Pass` and does not
  authorize a product API or Architecture Amendment. The gap itself is the
  truthful completion disposition for this leaf under the current T08 policy.
- PR #380 and its deleted public semantic/blob surface are not evidence for
  this reconciliation. The current evidence is only the surviving
  current-main production/test boundary and the controlled runs recorded above.

### Existing implementation delivery facts

The already-implemented T15 candidate was delivered by PR #374 with head
`4cee49887d858cb62612c601ddcc296d93e662b1` and merge
`bed2dac9947d5c5f92e0d530378f5be712e041a6`. Those facts are historical
implementation delivery facts, not this documentation-only reconciliation's
PR or merge result.

### Current-main verification fence

- T09 is **completed** on this current-main baseline. The effective central
  `validator_registry` length is **32**; the historical `len 11` statement is
  retained only in the explicitly historical evidence above.
- The focused `semantic_blob` suite is the required **11/11** run: eleven
  tests executed, zero failed, zero ignored, zero measured, and zero filtered
  out. The historical seven-test statement is retained only in the explicitly
  historical evidence above.
- The exact executable baseline under this reconciliation is
  `3c9d86912ea7f72818a11ffde1a5281b98e3c492`; this reconciliation changes only
  this ledger and leaves production and test code unchanged. The final
  docs-only candidate HEAD and the rerun results are supplied in the Executor
  handoff for this candidate.

### Reconciliation verification and handoff

- Final candidate base: `a898e5be6e33f5f448992c7ddb642af7336bc8f8`.
- Final candidate implementation baseline: `3c9d86912ea7f72818a11ffde1a5281b98e3c492`;
  the reconciliation descendant is docs-only and contains no production or
  test-code change.
- `bash tools/test.sh -p loom-validator --test semantic_blob -- --nocapture`:
  `11 passed, 0 failed, 0 ignored, 0 measured, 0 filtered out` on the
  current-main implementation candidate; this is the required 11/11 InMemory
  + PostgreSQL 18 run with no skip/ignore/filter bypass.
- `cargo fmt --all -- --check`, `cargo check -p loom-validator --all-targets`,
  `cargo clippy -p loom-validator --all-targets -- -D warnings`,
  `python3 tools/check_architecture.py`,
  `python3 tools/check_storage_sql_ownership.py`, and `git diff --check`:
  PASS on the current-main implementation candidate and docs-only
  reconciliation.
- Reconciliation PR: pending Leader action; none created by this Executor.
- Reconciliation Reviewer result: pending Leader action; not prefilled.
- Reconciliation required CI result: pending Leader action; not prefilled.
- Reconciliation merge SHA and post-merge current-main SHA: pending Leader
  action; not prefilled.
