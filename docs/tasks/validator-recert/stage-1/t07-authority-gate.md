---
task: VALR-T07
issue: 312
status: completed
depends_on: [310, 311]
created_at: 2026-08-26
started_at: 2026-08-26
completed_at: 2026-08-26
completion_pr: 341
merge_sha: 5f271fe6493890d31889bf2d5170ec6a57d80446
---

# VALR-T07 — Stage-1 Validator authority regression gate

Provide one integrated regression gate proving the six known Validator authority/evidence defects are closed together, not merely in isolated unit tests.

## Goal

Provide a single named, repeatable gate that mechanically proves all six Stage-1 regressions are closed together:

1. **single-pass:** a selected scenario is never executed twice by one CLI invocation;
2. **strict truth:** `Fail`/`Skipped`/`Unavailable` cannot return success under strict policy;
3. **selection truth:** explicit `unknown`/`empty` selection returns configuration error (`exit 2`);
4. **backend truth:** external endpoint + valid `LOOM_TEST_POSTGRES_URL` is not trusted `PostgreSQL` evidence;
5. **restart truth:** reconnect-only external context cannot pass `CV-003`/`CV-004` as real boundary restart;
6. **required-live truth:** only controlled `PostgreSQL` evidence can satisfy the live requirement.

The gate must be executable via `bash tools/validator-authority-gate.sh` (canonical) and its core via `cargo test -p loom-validator --test authority_gate --all-features`. It must internally assert the six classes with real harness/CLI checks, not merely list unassociated commands.

## Scope

Allowed:

- Validator integration/regression test files (`apps/loom-validator/tests/authority_gate.rs`);
- Minimal CI wiring to run the integrated gate (`tools/validator-authority-gate.sh`, `.github/workflows/ci.yml`);
- This ledger record.

Forbidden:

- No new production semantics, capability scenarios, storage-introspection API, or public contracts;
- No modification of T01–T06 completed Rust code, tests, configuration, or ledgers (if gate exposes a prior defect, stop and report the owning leaf);
- No `loom-core`/`loom-protocol`/`loom-capability`/`loom-agency`/`loom-runtime`/`loom-storage`/`loom-boundary` changes.

## Implementation

1. Added `apps/loom-validator/tests/authority_gate.rs` — the single integrated gate binary. It reuses T01–T06 public/test harness (`Runner`, `BackendContext`/`BackendHarness`, `execute_cli`, `lifecycle_registry`, `common::{InMemoryServer,PgServer}`, `CARGO_BIN_EXE_loom-validator` subprocess) and asserts the six classes:
   - `single_pass_normal_continues_and_fail_fast_stops_without_replay` — `Runner::run_selected`/`run_with_harness_selected`/`execute_cli` invocation counters prove exactly-once per scenario, `fail-fast` stops after first `Fail` without replay, report derives from same pass; covers `normal`/`best-effort` and `fail-fast`.
   - `strict_truth_fail_skipped_unavailable_are_nonzero` — `strict` with `Fail`/`Skipped`/`Unavailable` → `exit 1` / `!gate_passes()`, `strict+all Pass` → `0`, `best-effort` with `Fail` → `0`, `fail-fast` without `strict` does not change gate, `strict` without `fail-fast` runs full selection.
   - `selection_truth_unknown_and_empty_are_exit_2` — `RunnerError::UnknownScenarioIds`/`UnknownGroups`/`InvalidSelection`/`EmptySelection` and CLI/execute paths return `exit 2` for `CV-999`, `typo-group`, `world,` malformed, `unknown` group; `strict+typo` still `2`; `--required-live` with typo still `2`; subprocess verifies `exit 2` for both `--scenario` and `--group`; deterministic `no selector → all` preserved.
   - `backend_truth_external_not_upgraded_by_ambient_pg` — `BackendHarness::LoomClient` remains `External` even with ambient `LOOM_TEST_POSTGRES_URL`; subprocess with `LOOM_VALIDATOR_BASE_URL=http://127.0.0.1:1` plus valid and malformed `LOOM_TEST_POSTGRES_URL` still reports `backend_evidence=external`, `backend_evidence_trusted=false`, never `postgresql`; `required-live` external still fails `exit 1` with both URLs.
   - `restart_truth_reconnect_only_cannot_fake_and_controlled_passes` — generic `BackendContext::ReconnectOnly` fails `CV-003`/`CV-004` with `reconnect-only` evidence (including `InMemory` kind with `ReconnectOnly` proving orthogonality); `reconnect` via `restart()` does not upgrade capability; controlled `InMemoryServer` with `with_controlled_boundary_restart` passes `CV-003` with `controlled-boundary-restart` evidence; controlled `PostgreSQL` seam verified and live `PgServer` restart exercised when available; generic CLI subprocess `CV-003` on `external` never passes.
   - `required_live_truth_only_controlled_postgres_satisfies` — `required-live` with `PostgreSQL` all `Pass` → `0`, `InMemory`/`External` all `Pass` → `1`, `PG+Skipped`/`Unavailable`/`Fail` → `1`, `harness External` with `required_live` → `!gate_passes()`, selection errors still `2`, single-pass preserved, report-layer `InMemory all Pass` not a required-live pass; subprocess external + valid/malformed PG URL with `--required-live` → `exit 1`, `backend_evidence=external`.
   - `stage1_authority_gate_all_six_classes_are_exercised_together` — single-test smoke that invokes all six invariants together, proving the binary is one gate.

2. Added `tools/validator-authority-gate.sh` — clearly named, repeatable gate entry. It delegates to `bash tools/test.sh -p loom-validator --test authority_gate -- --nocapture` (the real assertions), then re-runs `backend_evidence`/`restart_evidence`/`required_live` suites for additional closure, validates `validator_ready --root docs/tasks/validator-recert/stage-1 --check`, and runs `check_architecture`/`check_storage_sql_ownership`/`cargo fmt --check`.

3. Minimal CI wiring in `.github/workflows/ci.yml`: added workflow path triggers for `docs/tasks/validator-recert/**`, added `Validator Stage-1 recert ledger` step (`validator_ready --root docs/tasks/validator-recert/stage-1 --check --format json`) and `Validator Stage-1 authority regression gate` step (`bash tools/validator-authority-gate.sh`) to the `rust` job so the gate runs on every PR/main push and is a required checks path.

No production source under `apps/loom-validator/src` or `crates/` was modified. No new capability scenario, no storage introspection API, no public contract change.

## Required tests

Gate binary (every `cargo test -p loom-validator --test authority_gate -- --nocapture` run):

- `single_pass_normal_continues_and_fail_fast_stops_without_replay` — proves single-pass for `run_selected`/`run_with_harness_selected`/`execute_cli` (normal double, fail-fast single, harness double, CLI counts).
- `strict_truth_fail_skipped_unavailable_are_nonzero` — strict gate truth and `fail-fast` vs `strict` independence.
- `selection_truth_unknown_and_empty_are_exit_2` — runner, library CLI, and subprocess selection errors (`CV-999`, `typo-group`, `world,`, `--required-live` variants) → `exit 2`; valid group/empty default preserved.
- `backend_truth_external_not_upgraded_by_ambient_pg` — `External` remains `external` with valid and malformed ambient `LOOM_TEST_POSTGRES_URL`; external+`--required-live` still `exit 1`.
- `restart_truth_reconnect_only_cannot_fake_and_controlled_passes` — reconnect-only blocked, `InMemory` controlled passes, `PgServer` controlled seam/live, subprocess generic `CV-003` not pass.
- `required_live_truth_only_controlled_postgres_satisfies` — `PostgreSQL` satisfies, `InMemory`/`External`/non-`Pass` do not; selection errors `2`; report layer; subprocess external+PG URL with `--required-live` → `1`.
- `stage1_authority_gate_all_six_classes_are_exercised_together` — one-test six-class smoke.

Reused focused suites (still green, invoked by gate wrapper and by `cargo test --workspace`):

- `cargo test -p loom-validator --lib` — 150+ unit tests including T01 single-pass counters, T02 strict/policy, T03 selection, T04 evidence, T06 required-live, reports, backend.
- `cargo test -p loom-validator --test backend_evidence` — 1 test, generic endpoint never infers `postgres` from ambient.
- `cargo test -p loom-validator --test restart_evidence` — 6 tests, reconnect-only vs controlled boundary restart.
- `cargo test -p loom-validator --test required_live` — 3 tests, external+PG URL fails `required-live`, selection `2`.
- `cargo test -p loom-validator --test lifecycle` / `replay_fork` / `runtime_authority` — live harness paths.

Ledger/CI wiring:

- `python3 tools/validator_ready.py --root docs/tasks/validator-recert/stage-1 --check --format json` — no violations, T07 `in_progress` with satisfied deps `310`/`311`.
- `python3 tools/check_architecture.py` / `check_storage_sql_ownership.py` — DAG and SQL ownership pass.
- `cargo fmt --all -- --check`, `cargo check/clippy --workspace --all-targets --all-features`, `cargo deny` via CI.

## Acceptance

- [x] All six regression classes are exercised in one integrated gate (`apps/loom-validator/tests/authority_gate.rs` + `bash tools/validator-authority-gate.sh`; CI step `Validator Stage-1 authority regression gate`).
- [x] No expected live requirement is satisfied by skipped/unavailable evidence (strict and `required-live` gate checks).
- [x] No external endpoint is relabelled `PostgreSQL` by ambient environment state (`backend_evidence=external` with valid/malformed `LOOM_TEST_POSTGRES_URL`).
- [x] Gate runs in repository CI (`.github/workflows/ci.yml` `rust` job) or an equivalent required CI path.
- [x] Review is complete and all CI checks are finished successfully.
- [x] Completion evidence contains PR, merge SHA and exact gate results.

## Verification Evidence

- `cargo fmt --all -- --check` → passed
- `cargo check --workspace --all-targets --all-features` → passed
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` → passed
- `cargo clippy -p loom-validator --all-targets --all-features -- -D warnings` → passed
- `cargo test -p loom-validator --lib --all-features` → 150 passed, 0 failed
- `bash tools/test.sh -p loom-validator --test authority_gate -- --nocapture` → passed (7 tests: single_pass/strict/selection/backend/restart/required_live/stage1_gate)
- `bash tools/test.sh -p loom-validator --test backend_evidence -- --nocapture` → passed (1)
- `bash tools/test.sh -p loom-validator --test restart_evidence -- --nocapture` → passed (6)
- `bash tools/test.sh -p loom-validator --test required_live -- --nocapture` → passed (3)
- `bash tools/test.sh --workspace --all-features` → passed (150 lib + 1+3+6+4+2 + lifecycle/replay_fork/runtime_authority)
- `python3 tools/check_architecture.py` → passed (Loom architecture dependency policy: OK)
- `python3 tools/check_storage_sql_ownership.py` → passed (storage SQL ownership check passed)
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert/stage-1 --check --format json` → `valid=true`, `violations=[]`, `record_count=7`, `ready=[]`, `blocked=[]` (all VALR-T01..T07 `completed`)
- `bash tools/validator-authority-gate.sh` → passed (canonical gate: authority_gate 7/7, backend_evidence 1/1, restart_evidence 6/6, required_live 3/3; validator_ready recert valid; arch/storage/fmt)
- PR #341 https://github.com/6spot/Loom/pull/341 — head `42994efa11d717a34303be6e42dcb04f34f70568`, base `6e3ffbe740239a35ba8f5193f51ce1462059ce46`
- Merge SHA `5f271fe6493890d31889bf2d5170ec6a57d80446` at `2026-08-26T16:12:28Z` (GitHub merge commit)
- Final Reviewer `01a03ed7-3eee-7538-bf5b-d6a3e28669fe` → approved on `42994efa...` (all AC-1..AC-6 verified, D-002 fixed)
- Final workflow run `32986487501` bound to `42994efa11d717a34303be6e42dcb04f34f70568` → `Rust checks` terminal success + `PostgreSQL 18 persistence contract` terminal success (jobs 2/2)
- GitHub issue #312 auto-closed by merge; Leader compensated close, no extra mapping change

## Progress Log

- 2026-08-26 — Created T07 ledger as `in_progress` with empty `completed_at`/`completion_pr`/`merge_sha` and unchecked acceptance; added integrated gate `apps/loom-validator/tests/authority_gate.rs` proving six classes together with real harness + CLI-subprocess assertions; added named gate wrapper `tools/validator-authority-gate.sh`; wired CI in `.github/workflows/ci.yml` (path triggers + `Validator Stage-1 authority regression gate` step + recert `validator_ready` check). No T01–T06 production code, tests, or ledgers modified.
- 2026-08-26 — Fix D-002: `selection_truth_unknown_and_empty_are_exit_2` now asserts explicit empty `world,` via `execute_cli` and subprocess (`--group world,`, `--strict --group world,`, `--required-live --group world,`) all return `exit 2`; gate remains single entry.
- 2026-08-26 — Post-merge ledger completion audit (follow-up PR from `5f271fe6493890d31889bf2d5170ec6a57d80446`): set `status: completed`, `completed_at: 2026-08-26`, `completion_pr: 341`, `merge_sha: 5f271fe6493890d31889bf2d5170ec6a57d80446`, checked all six Acceptance, recorded Verification Evidence (Reviewer `01a03ed7-3eee-7538-bf5b-d6a3e28669fe`, workflow `32986487501` 2/2 success, canonical gate 7/7, merge `5f271fe` at `2026-08-26T16:12:28Z`), `validator_ready --root docs/tasks/validator-recert/stage-1 --check` → `valid=true` `violations=[]` 7 records all completed.
