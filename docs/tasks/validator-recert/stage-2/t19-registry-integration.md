---
task: VALR-T19
issue: 324
status: in_progress
depends_on: [315, 316, 317, 318, 319, 320, 321, 322, 323]
created_at: 2026-08-26
started_at: 2026-08-27
completed_at:
completion_pr:
merge_sha:
---

# VALR-T19 — Integrate completed Stage-2 suites into the Validator registry

This leaf is the single central composition point for the Stage-2 Validator
scenarios. It consumes the completed suite descriptors and executors already
present on the current main baseline; it does not alter suite semantics,
Runtime/Storage behavior, or the frozen T08 allocation.

## Central composition

`validator_registry()` preserves the Stage-1 `CV-001..CV-011` registration
order/IDs and then composes these T08-implementable Stage-2 rows once:

| Owner | Registered IDs | Blocked/unregistered IDs |
| --- | --- | --- |
| T10 world binding | CV-012..CV-014 | — |
| T11 action/ingress | CV-015..CV-017 | — |
| T12 scheduler | CV-020 | CV-018..CV-019 (no public schedule/claim/fence surface) |
| T13 world time | CV-021..CV-024 | — |
| T14 query/catalog | CV-025..CV-027 | — |
| T15 semantic/blob | CV-030 | CV-028..CV-029 (no public projection/blob API) |
| T16 provenance | CV-031..CV-033 | — |
| T17 agency | — | CV-034..CV-037 (no public/controlled agency execution/claim surface) |
| T18 change feed | CV-038..CV-040 | — |

The resulting exact registry set is 32 IDs: `CV-001..CV-017`, `CV-020..CV-027`,
`CV-030..CV-033`, and `CV-038..CV-040`. `ScenarioRegistry`'s BTree ordering
provides deterministic enumeration and duplicate rejection. T11's merged
CV-017 evidence is now composed at this central boundary; T12/T15 expose only
their implementable descriptors, and T17 has no executable descriptors.

CLI dispatch is composed for every registered Stage-2 ID and routes to the
owning suite executor. No fallback “registered without executor” path is used
by any registered ID. Listing, group selection, `--all`, and report selection
continue to use the existing generic `Runner`/`ScenarioRegistry` paths.

## Acceptance mapping

- AC-01 / R-01: implementation candidate `9b5c74b6dd145454cde83a5ffbd5280eb02b442b`
  starts from current `origin/main` `95f7e7a0233cfa917d0c9656b990fd2af4996874`;
  T11's merged CV-017 descriptor/executor is composed from
  `action_ingress::{descriptors,execute}`.
- AC-02: Stage-1 `CV-001..CV-011` remain present and unchanged.
- AC-03: all currently evidenced T08-implementable T10–T18 rows are registered
  exactly once; CV-017 is included from T11's real evidence, while blocked rows
  CV-018/019/028/029/034..037 remain absent and no placeholder is introduced.
- AC-04: registry tests assert exact IDs, deterministic repeated enumeration,
  duplicate-free count, exact group membership, unknown-group errors, complete
  `--all`, and central dispatch result coverage.
- AC-05: suite-specific behavior remains in dedicated modules; central files
  only compose/register and route descriptors to their existing executors.

## Allowed files changed

- `apps/loom-validator/src/lib.rs` — central Stage-2 composition and registry tests.
- `apps/loom-validator/src/cli.rs` — central registered-scenario dispatch.
- `apps/loom-validator/src/query_catalog.rs` and
  `apps/loom-validator/src/semantic_blob.rs` — registry-fence assertions only;
  no suite execution semantics changed.
- `apps/loom-validator/tests/{action_ingress,agency,change_feed,provenance,query_catalog,scheduler,semantic_blob,world_binding,world_time}.rs`
  — registry-fence assertions updated to the T19 central composition; no
  dedicated scenario behavior changed.
- `docs/tasks/validator-recert/stage-2/t19-registry-integration.md` — this ledger.

No T10–T18 suite execution code, core, Runtime, Storage, API, or shared
harness file is changed by this candidate.

## Verification evidence

Candidate implementation commit: `9b5c74b6dd145454cde83a5ffbd5280eb02b442b`.
Base: `origin/main` = `95f7e7a0233cfa917d0c9656b990fd2af4996874`.

- `cargo fmt --all -- --check` — PASS.
- `cargo check -p loom-validator --all-targets` — PASS.
- `cargo clippy -p loom-validator --all-targets -- -D warnings` — PASS.
- `cargo test -p loom-validator --lib stage2_ -- --test-threads=1` — PASS;
  exact registry/group assertions, 2 passed, 0 failed.
- `cargo test -p loom-validator --lib all_selection_is_complete_and_uses_registered_executor_paths -- --test-threads=1` — PASS; 1 passed, 0 failed.
- `bash tools/test.sh -p loom-validator --test action_ingress -- --test-threads=1` — PASS; 11 passed, 0 failed, 0 ignored, including CV-017 InMemory and PG restart evidence.
- Standalone Validator integration targets — PASS: agency 1, authority_gate 7,
  backend_evidence 1, change_feed 7, lifecycle 3, provenance 9,
  query_catalog 7, replay_fork 4, required_live 3, restart_evidence 6,
  runtime_authority 2, scheduler 4, semantic_blob 7, world_binding 10,
  world_time 10; all had 0 failures and 0 ignored. The fixture-only
  `query_catalog_causal_fixture` target is not a required behavior target.
- `LOOM_TEST_POSTGRES_URL=<fresh PG18 temp DB> bash tools/validator-pg18-gate.sh` — PASS;
  T20 gate 2 passed, 10/10 required-live rows passed, 0 failed/skipped/unavailable.
- `cargo run -q -p loom-validator -- --list` — PASS; actual output enumerated
  exactly 32 IDs in deterministic order, including CV-017 and excluding
  CV-018/019/028/029/034..037.
- `python3 tools/check_architecture.py` — PASS.
- `python3 tools/check_storage_sql_ownership.py` — PASS.
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json` — FAIL;
  report `valid=false`, with T10/T11/T13–T16/T18 still `in_progress`, T17
  explicitly architecture-blocked, and T19 dependencies not all completed.
- `bash tools/test.sh -p loom-validator --all-targets -- --test-threads=1` — FAIL
  on the existing shared PG control DB at T20 CV-016 because fixed
  `t11.cv016.key1` already existed and first submit returned `IdempotencyConflict`.
  A fresh-database aggregate rerun was interrupted after an unrelated
  `cv016_via_pg_with_restart_if_available` wait despite its ingress row being
  Completed; all affected behavior was then re-executed successfully by the
  standalone targets and fresh-database T20 gate above. These aggregate command
  outcomes remain recorded as non-pass evidence.
- `git diff --check` — PASS; final allowed-file boundary is recorded after the
  ledger commit below.

## Progress log

- 2026-08-28 — From `origin/main` `95f7e7a`, composed T11 CV-017 into the
  central registry and dispatch, updated exact/group/`--all`/count assertions,
  and preserved blocked CV-018/019/028/029/034..037 exclusions. No suite
  execution, core/runtime/storage/API, or T08 allocation changes were made.
