---
task: VALR-T01
issue: 306
status: in_progress
depends_on: []
created_at: 2026-08-26
started_at: 2026-08-26
completed_at:
completion_pr:
merge_sha:
---

# VALR-T01 — Make Validator CLI execution single-pass

Guarantee that one Validator CLI invocation executes each selected scenario at most once.

## Goal

Route CLI execution through the existing Runner single-pass path, removing the duplicate selection execution that occurred under `fail-fast`/`strict` and ensuring report generation consumes the results from that one execution only.

## Current defect

The `run_from_args` CLI path executed the whole selection, built a report, and under `fail-fast`/`strict` re-executed the same selection to stop at the first failure. Validator scenarios are stateful, so the second pass could create extra Worlds/events/revisions and produce evidence that no longer corresponds to the first failure.

## Scope

Allowed:
- `apps/loom-validator/src/` only where required to route CLI execution through the existing Runner single-pass path;
- Validator unit/integration tests proving invocation count/order;
- This task's Task Ledger record.

Forbidden:
- Do not change strict gate semantics (VALR-T02);
- Do not change backend identity/restart evidence (other leaves);
- Do not add new capability scenarios;
- Do not redesign architecture or storage/runtime authority.

## Implementation

1. Identified canonical Runner path `Runner::run_selected` (single-pass with optional early stop) and its harness counterpart `run_with_harness`.
2. Removed duplicate scenario execution from `apps/loom-validator/src/cli.rs:run_from_args` (`apps/loom-validator/src/cli.rs:556-626` double loop) and replaced it with a single call to `Runner::run_with_harness_selected` (`apps/loom-validator/src/runner.rs:364`) which is the single execution authority.
3. Extended `Runner` with `run_with_harness_selected` that:
   - starts a fresh `BackendContext` per selected scenario via `harness.start`/`dispose`;
   - preserves the `supported_backends` prerequisite guard (`run_with_harness` already had: if `!supported_backends.contains(backend)` → `ScenarioResult::prerequisite` without calling executor);
   - respects `fail_fast` in the same single pass (`break` on `is_fail`);
   - preserves deterministic ordering (`selection` is already resolved sorted by `resolve_with_groups`);
   - returns `ValidationReport::from_results_with_policy(...).with_backend(...).with_selected_scenario_ids(...)` consuming only the one execution's results.
4. Preserved best-effort continuation when `fail-fast` is disabled and deterministic ordering.
5. `execute_cli` already delegated to `Runner::run_selected`; no change needed there beyond regression coverage.

## Required tests

Regression coverage proves (preferring executor-call counters / test doubles):

- two-scenario selection invokes each scenario exactly once in normal mode;
- when the first scenario fails under fail-fast, the second is never invoked;
- the failing first scenario itself is invoked exactly once;
- report contents are produced from the same execution pass;
- unsupported backend → prerequisite without executor invocation (retained from `run_with_harness`).

Added in `apps/loom-validator/src/runner.rs`:
- `single_pass_two_scenarios_invokes_each_exactly_once_in_normal_mode`
- `fail_fast_first_failure_second_never_invoked_and_first_exactly_once`
- `harness_selected_single_pass_counts_and_report_from_same_pass`

Added in `apps/loom-validator/src/cli.rs`:
- `cli_single_pass_two_scenarios_each_exactly_once_in_normal_mode`
- `cli_fail_fast_first_failure_second_never_invoked_and_first_exactly_once`
- `cli_report_contents_are_from_same_execution_pass`

Existing `run_with_harness` prerequisite guard retained and re-verified with new selected-path guard.

## Acceptance

- [x] No CLI branch executes the same selected scenario a second time.
- [x] Existing Runner remains the single execution authority (`run_with_harness_selected` / `run_selected`).
- [x] Normal mode still runs later scenarios after a failure.
- [x] Fail-fast stops after the first failure without replaying prior scenarios.
- [x] Focused regression tests pass.
- [x] `cargo fmt --check`, relevant `cargo test`, `cargo clippy` pass.
- [ ] Review and CI are complete before marking the task completed.

## Verification Evidence

- `cargo fmt --all -- --check` → passed
- `cargo clippy -p loom-validator --all-targets --all-features -- -D warnings` → passed
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` → passed
- `cargo test -p loom-validator --lib --all-features` → 102 passed (including 7 new single-pass counter tests)
- `python3 tools/check_architecture.py` → passed
- `python3 tools/check_storage_sql_ownership.py` → passed

## Progress Log

- 2026-08-26 — Identified `run_from_args` double execution (`apps/loom-validator/src/cli.rs:556-626`) vs `Runner::run_selected` single-pass authority; replaced CLI harness double loop with `Runner::run_with_harness_selected` single pass and added counter-based regression tests.
- 2026-08-26 — Rework per LEADER-PRECHECK: added `docs/tasks/validator-recert/stage-1/t01-single-pass-cli.md` ledger and retained `supported_backends` prerequisite guard in `run_with_harness_selected`.

