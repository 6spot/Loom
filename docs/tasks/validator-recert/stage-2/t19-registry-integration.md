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
| T11 action/ingress | CV-015..CV-016 | CV-017 (no public fault injection) |
| T12 scheduler | CV-020 | CV-018..CV-019 (no public schedule/claim/fence surface) |
| T13 world time | CV-021..CV-024 | — |
| T14 query/catalog | CV-025..CV-027 | — |
| T15 semantic/blob | CV-030 | CV-028..CV-029 (no public projection/blob API) |
| T16 provenance | CV-031..CV-033 | — |
| T17 agency | — | CV-034..CV-037 (no public/controlled agency execution/claim surface) |
| T18 change feed | CV-038..CV-040 | — |

The resulting exact registry set is 31 IDs: `CV-001..CV-016`, `CV-020..CV-027`,
`CV-030..CV-033`, and `CV-038..CV-040`. `ScenarioRegistry`'s BTree ordering
provides deterministic enumeration and duplicate rejection. T11's local
blocked CV-017 descriptor is explicitly excluded at this central boundary;
T12/T15 expose only their implementable descriptors, and T17 has no executable
descriptors.

CLI dispatch is composed for every registered Stage-2 ID and routes to the
owning suite executor. No fallback “registered without executor” path is used
by any registered ID. Listing, group selection, `--all`, and report selection
continue to use the existing generic `Runner`/`ScenarioRegistry` paths.

## Acceptance mapping

- AC-01 / R-01: current `origin/main` is
  `1488dde820e28af46e889da09a20994518c9f797`, which contains the merged T13
  delivery; `CV-021..CV-024` are composed from `world_time::{descriptors,execute}`.
- AC-02: Stage-1 `CV-001..CV-011` remain present and unchanged.
- AC-03: all T08-implementable T10–T18 rows are registered exactly once;
  blocked rows remain absent and no placeholder scenario is introduced.
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

- `git fetch origin main` — PASS; refreshed `origin/main` to
  `1488dde820e28af46e889da09a20994518c9f797`.
- `cargo fmt --all -- --check` — PASS.
- `cargo check -p loom-validator --all-targets` — PASS.
- `cargo clippy -p loom-validator --all-targets -- -D warnings` — PASS.
- `LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_control cargo test -p loom-validator --all-targets -- --test-threads=1` — PASS for all required behavior; 165 library tests, 0 binary tests, and every non-empty integration target passed with 0 failures and 0 ignored tests, including live PostgreSQL paths for CV-021..CV-024. The fixture-only `query_catalog_causal_fixture` target ran 0 tests and is not a required behavior target.
- `cargo run -q -p loom-validator -- --list` — PASS; actual CLI output enumerated exactly the 31 registered IDs in deterministic order, including CV-021..CV-024 and excluding all blocked T08 rows.
- `cargo test -p loom-validator --lib stage2_ -- --test-threads=1` — PASS;
  exact registry and group tests, 2 passed, 0 failed.
- `cargo test -p loom-validator --lib all_selection_is_complete_and_uses_registered_executor_paths -- --test-threads=1` — PASS; 1 passed, 0 failed.
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json` — NOT PASS; other T10/T11/T13–T18 ledgers still carry `in_progress`/`blocked` frontmatter while their Multica dependencies are complete. This T19 candidate does not modify those leaf ledgers.
- `python3 tools/check_architecture.py` — PASS.
- `python3 tools/check_storage_sql_ownership.py` — PASS.
- `git diff --check` and allowed-file name/status boundary — PASS on the final
  candidate; `git status --porcelain` is empty.

## Progress log

- 2026-08-27 — Rebased the executor branch to the current `origin/main` T13
  merge baseline, composed implementable T10–T18 descriptors, routed central
  dispatch, and added registry-focused exact-set/group/`--all` tests. Blocked
  T08 rows remain excluded; no placeholder or duplicate ID was added.
