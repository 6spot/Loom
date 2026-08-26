---
task: VALR-T02
issue: 308
status: in_progress
depends_on: [306]
created_at: 2026-08-26
started_at: 2026-08-26
completed_at:
completion_pr:
merge_sha:
---

# VALR-T02 — Separate strict gate policy from fail-fast execution

Make `--strict` mean “the selected validation gate passes only when every selected scenario satisfies policy,” while `--fail-fast` only controls whether execution stops after the first hard failure.

## Goal

Separate strict gate policy from fail-fast execution control. `--strict` must select the strict report/gate policy independently, and `--fail-fast` must only affect single-pass execution stopping. After the single execution pass from VALR-T01, exit status must be computed from the report policy/gate rather than `has_failures()` only.

## Current defect

`--strict` was treated as a fail-fast alias, while exit status only checked `Fail`. `Skipped` and `Unavailable` could therefore still return success even when strict semantics require every selected scenario to pass.

## Scope

Allowed:
- Validator CLI option parsing (`apps/loom-validator/src/cli.rs`);
- `ValidationPolicy`/report gate evaluation (`apps/loom-validator/src/reports.rs`);
- Focused CLI/report tests;
- This task's Task Ledger record.

Forbidden:
- Do not change backend evidence classification (VALR-T04);
- Do not implement required-live semantics beyond preserving a clean policy hook (VALR-T06);
- Do not add scenarios;
- Do not rework T01 single-pass execution or introduce T03/T06 semantics.

## Implementation

1. Split `CliArgs` into independent `fail_fast: bool` and `strict: bool`. Updated `parse_args` to handle `--fail-fast` and `--strict` separately; combined `| "--strict"` alias removed. Added `is_strict()` accessor and updated `CliAction::Run` to carry both flags.
2. Updated `help_text` and module docs to document `--fail-fast` as execution-control only and `--strict` as strict gate (rejects `Fail`, `Skipped`, `Unavailable`, independent of `--fail-fast`). Updated EXIT CODES to reflect best-effort vs strict.
3. Extended `ValidationReport` with `with_policy(ValidationPolicy)` to allow CLI to set report policy after single-pass execution without replaying scenarios.
4. Preserved T01 single-pass execution: `execute_cli` continues to use `Runner::run_selected(..., fail_fast)` and `run_from_args` continues to use `Runner::run_with_harness_selected(..., fail_fast)` exactly once. No duplicate execution path reintroduced.
5. Routed CLI exit status through strict gate: after single execution, report policy is set to `ValidationPolicy::strict()` when `--strict` else `best_effort()`. For harness path, `BackendHarness` policy is set accordingly before `run_with_harness_selected` so `ValidationReport::from_results_with_policy(..., harness.policy())` already carries the correct policy. Exit is `EXIT_SCENARIO_FAILURE` iff `strict && !report.gate_passes()`, otherwise `EXIT_SUCCESS`. This makes `Fail`, `Skipped`, `Unavailable` all fail strict gate while best-effort (non-strict) remains exit 0, and `fail_fast` never changes gate policy.
6. No changes to backend evidence, restart evidence, required-live, or scenario definitions.

## Required tests

Focused coverage (CLI/report/policy) proves:

- `--strict` is no longer an alias for `--fail-fast`; both parse independently and together.
- `strict + all Pass` => exit 0; `strict + Fail` => nonzero; `strict + Skipped` => nonzero; `strict + Unavailable` => nonzero (via `ValidationPolicy::strict()` gate).
- `fail-fast` without `strict` still stops execution after first hard `Fail` but does not change gate (best-effort exit remains 0, full proof via counter tests).
- `strict` without `fail-fast` executes the full selection yet returns nonzero when any selected result is non-pass (full selection counter proof).
- Existing single-pass invocation-count tests remain green.

Added in `apps/loom-validator/src/cli.rs`:
- `parse_strict_and_fail_fast_are_independent`
- `strict_all_pass_exits_zero`
- `strict_fail_exits_nonzero`
- `strict_skipped_exits_nonzero`
- `strict_unavailable_exits_nonzero`
- `fail_fast_without_strict_stops_but_gate_unchanged`
- `strict_without_fail_fast_executes_all_but_still_fails`
- `strict_sets_policy_gate_and_does_not_imply_fail_fast`
- `non_strict_best_effort_with_skipped_still_succeeds`

Updated in `apps/loom-validator/src/cli.rs`:
- `parse_alias_strict` now asserts `strict` true and `fail_fast` false
- `parse_all_and_fail_fast` asserts `strict` false
- `fail_fast_stops_and_exits_1` now requires `strict: true` for exit 1 case
- `help_text_is_documented` now checks `--strict`

Added in `apps/loom-validator/src/reports.rs`:
- `strict_gate_rejects_fail_skipped_unavailable_and_passes_all_pass`
- `with_policy_overrides_gate_policy`

Retained:
- `single_pass_*` and `harness_selected_*` counter tests from T01
- `unavailable_result_never_passes_any_gate` and required-live tests

## Acceptance

- [x] `--strict` is no longer an alias for `--fail-fast`; both parse independently and can be combined.
- [x] Strict exit status uses policy/gate evaluation; `Skipped` and `Unavailable` cannot false-green strict mode.
- [x] `fail-fast` only influences execution stopping; non-strict gate remains best-effort.
- [x] Execution remains single-pass (T01 path reused, no replay).
- [x] Focused tests and repository checks pass (`cargo fmt --check`/`cargo test -p loom-validator`/`cargo clippy`/architecture checks).
- [ ] Review and CI are complete before marking the task completed.

## Verification Evidence

- `cargo fmt --all -- --check` → passed (clean)
- `cargo test -p loom-validator --lib --all-features` → 119 passed, 0 failed (includes 11 new strict/policy tests + 7 T01 single-pass tests)
- `cargo clippy -p loom-validator --all-targets --all-features -- -D warnings` → passed
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` → passed
- `python3 tools/check_architecture.py` → passed (Loom architecture dependency policy: OK, storage SQL ownership check passed)
- `python3 tools/check_storage_sql_ownership.py` → passed

## Progress Log

- 2026-08-26 — Split `CliArgs` strict/fail_fast, updated `help_text`/`decide_action`, added `ValidationReport::with_policy`, routed `execute_cli`/`run_from_args` exit through `strict && !gate_passes()` while keeping T01 single-pass (`run_selected`/`run_with_harness_selected` with `fail_fast` only). Added focused CLI/report/policy tests for strict vs fail-fast independence.
