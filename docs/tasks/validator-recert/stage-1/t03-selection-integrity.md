---
task: VALR-T03
issue: 309
status: in_progress
depends_on: [308]
created_at: 2026-08-26
started_at: 2026-08-26
completed_at:
completion_pr:
merge_sha:
---

# VALR-T03 — Reject explicit zero-scenario selections

Prevent typoed or explicit selections that resolve to zero scenarios from succeeding as a false-green validation run.

## Goal

Ensure explicit selectors that resolve to zero scenarios, unknown scenario IDs, and unknown groups are treated as configuration errors (exit 2) with clear selector error text, while preserving the no-selector default (`--all`) and valid selector semantics.

## Current defect

Unknown groups intentionally resolved to no matches and the CLI printed `0 scenario(s) selected` then exited successfully. A misspelled group could therefore validate nothing and still look green. The runner's `resolve_with_groups` returned `Ok([])` for explicit unknown groups and the CLI's empty-selection branch returned `EXIT_SUCCESS`, masking configuration errors.

## Scope

Allowed:
- Validator selection resolution (`apps/loom-validator/src/runner.rs`) and CLI error mapping (`apps/loom-validator/src/cli.rs`);
- Focused parser/runner/CLI tests;
- This task's ledger record.

Forbidden:
- Do not alter strict/backend/restart semantics;
- Do not add new scenario groups;
- Do not rewrite existing scenario IDs;
- Do not modify backend evidence, restart, or required-live logic.

## Implementation

1. Extended `RunnerError` in `apps/loom-validator/src/runner.rs:40` with `UnknownGroups(Vec<String>)` and `EmptySelection(String)`; updated `Display` to emit `unknown group(s):` and `invalid selection:` prefixes for automation logs.
2. Replaced `expand_csv` with `expand_groups_checked` to treat empty group entries as `InvalidSelection("empty group")`, matching scenario-ID strictness.
3. Updated `Runner::resolve_with_groups` (`apps/loom-validator/src/runner.rs:159`):
   - `all == true` still returns all; empty IDs+groups still defaults to all (preserves `no selector` behavior).
   - Validates unknown scenario IDs as before (`UnknownScenarioIds`).
   - Computes known capability areas from registry; any requested group not in that set returns `UnknownGroups` sorted/deduped (covers typo, single and comma-separated multi-unknown).
   - Builds deterministic `selected_ids` union (explicit IDs + group-matched IDs) and returns `EmptySelection` with `no scenarios matched selection: groups=[...] ids=[...]` when explicit selectors yield zero (defensive fallback; unknown groups already error earlier).
   - Preserves deterministic sorted ordering and deduping.
4. Updated CLI error mapping in `apps/loom-validator/src/cli.rs:388` and `apps/loom-validator/src/cli.rs:582`:
   - `RunnerError` (including new variants) already maps to `EXIT_RUNNER_ERROR` (2) with `error: {err}` and optional machine-report `runner_config_failure`.
   - Added defensive guard in both `execute_cli` (`apps/loom-validator/src/cli.rs:412`) and `run_from_args` (`apps/loom-validator/src/cli.rs:590`) for `selection.is_empty()` when explicit selectors were present: emits `error: no scenarios matched selection: groups=[...] ids=[...]` and returns `EXIT_RUNNER_ERROR` (2), preventing any residual green empty run.
   - `selection.is_empty()` with no explicit selector remains success (`0 scenario(s) selected`) for empty registry case.
5. Preserved T01 single-pass and T02 strict/fail-fast semantics: `run_selected`/`run_with_harness_selected` unchanged; `strict && !gate_passes()` still drives exit 1, strict+typo cannot return 0 because typo now exits 2 before execution.

## Required tests

Focused coverage proves:

- `unknown group => exit 2` (runner error text contains `unknown group` and group name; CLI returns 2);
- `unknown scenario ID => exit 2` (existing + new CLI test with `CV-999`);
- `explicit selection resolving to empty => exit 2` (unknown group path + defensive empty guard);
- `valid group => deterministic selection` (world group still yields `CV-001, CV-003` sorted);
- `no selector => default all` (empty args still runs all 3 in test registry);
- `strict + typo cannot return 0` (CLI with `strict + typo` returns 2, never 0 or 1).

Added in `apps/loom-validator/src/runner.rs`:
- `unknown_group_is_config_error`
- `unknown_group_mixed_with_valid_is_still_error`
- `unknown_group_with_comma_separated_multiple_unknowns`
- `explicit_empty_selection_is_config_error`
- `empty_group_string_is_invalid_selection`
- `valid_group_still_resolves_deterministically`
- `no_selector_returns_all_deterministically`

Added in `apps/loom-validator/src/cli.rs`:
- `unknown_group_returns_exit_2`
- `explicit_empty_selection_returns_exit_2`
- `unknown_scenario_id_returns_exit_2_with_clear_text`
- `valid_group_runs_deterministic_selection`
- `no_selector_retains_default_all_behavior`
- `strict_with_typo_cannot_return_zero`
- `strict_with_unknown_group_cannot_return_zero`
- `decide_action_unknown_group_is_runner_error`
- `valid_selection_still_deterministic_after_t03`

## Acceptance

- [x] Explicit zero selection is never a successful validation run.
- [x] Error text identifies the invalid selector clearly enough for automation logs (`unknown scenario id(s):`, `unknown group(s):`, `no scenarios matched selection:`) and exit code is 2.
- [x] No valid existing selector changes meaning; valid group/scenario and no-selector behavior remain deterministic.
- [x] Tests cover group and scenario typo paths.
- [x] Relevant fmt/test/clippy checks pass; ledger evidence recorded.
- [ ] Review and CI are complete before marking the task completed (pending independent T03 integration PR, will be updated after merge).

## Verification Evidence

- `cargo fmt --all -- --check` → passed (after `cargo fmt --all`)
- `cargo test -p loom-validator --lib --all-features` → 135 passed, 0 failed (includes 7 new runner + 9 new CLI selection-integrity tests)
- `cargo clippy -p loom-validator --all-targets --all-features -- -D warnings` → passed
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` → passed
- `python3 tools/check_architecture.py` → passed (DAG OK, storage SQL ownership OK)
- `python3 tools/check_storage_sql_ownership.py` → passed

## Progress Log

- 2026-08-26 — Fixed `Runner::resolve_with_groups` to reject unknown groups and explicit empty selections as configuration errors; hardened `execute_cli`/`run_from_args` empty-selection guard to exit 2 with selector-aware message; added focused runner/CLI tests for T03 required semantics; created this ledger.
- 2026-08-26 — Rework D-1 (independent T03 integration): 实现已随 `4e4cd9244ee551b0ac25eed49e8b4ad9c52e8506` 交付，本分支仅为依赖集成，按 ledger 合约保持 `status: in_progress` 并清空 `completed_at`/`completion_pr`/`merge_sha`，待独立 PR 合并后以真实 `completion_pr`/`merge_sha` 补齐；未伪造 PR/SHA，未改运行时语义。
