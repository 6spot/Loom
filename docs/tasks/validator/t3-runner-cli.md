---
task: VAL-T3
issue: 255
status: completed
depends_on: ["VAL-T2"]
created_at: 2026-08-24
started_at: 2026-08-25
completed_at: 2026-08-25
completion_pr: 269
merge_sha: f84fd1f387ba2da43f28c489071c1013549b8217
---
# VAL-T3 — Implement validator runner CLI and scenario selection

Implement the runner that deterministically selects and executes registered validator scenarios.

## Acceptance

- [x] list/single/multi/all selection works;
- [x] unknown IDs return a runner/config error rather than a fake scenario failure;
- [x] a failing scenario does not prevent later selected scenarios from running in normal mode;
- [x] exit semantics are documented and tested;
- [x] standard Rust gates pass.

## Scope

- CLI supports `list` (`--list`/`-l`), single-ID selection (`--scenario`/`-s` or positional), repeated IDs / group selection (comma-separated, repeated flags, `--group <capability-area>`), and all-available execution (no selection or `--all`);
- deterministic execution ordering (sorted by stable `CV-` ID, deduplicated regardless of input order);
- clear separation between scenario execution result (`pass`/`fail`/`skipped`/`unavailable` collected in `ValidationReport`) and process/runner failure (`RunnerError::UnknownScenarioIds`, invalid usage);
- normal development mode continues after a failed scenario and collects remaining results (default, exit `0`);
- optional explicit `--fail-fast` / `--strict` for CI diagnostics (stop after first `fail`, exit `1`); not the Task Ledger feedback default;
- concise human-readable summary via `ValidationReport::summary_line()` and per-scenario lines; runner errors to stderr.

No direct Runtime/Storage authority, shadow API, or broad scenario coverage is part of this runner leaf. Machine-readable deterministic reports are handled by VAL-T5.

## Progress Log

- 2026-08-25 — Implemented deterministic runner selection (`Runner::resolve_with_groups`, `resolve_ids`, `run_selected`, `run_with_selection`), `RunnerError` separation, `ValidationReport` summary helpers, CLI parsing (`--list`, `--scenario`, `--group`, `--all`, `--fail-fast`/`--strict`, positional IDs, `--help`), exit semantics (`0` success, `1` scenario failure with `--fail-fast`, `2` runner/config error), and concise summary output.

## Verification Evidence

- `cargo fmt --all -- --check` → passed (after `cargo fmt --all`).
- `cargo check -p loom-validator --all-targets --all-features` → passed.
- `cargo check --workspace --all-targets --all-features` → passed.
- `cargo clippy -p loom-validator --all-targets --all-features -- -D warnings` → passed.
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` → passed.
- `cargo test -p loom-validator` → 56 tests passed (including new selection, ordering, unknown-ID runner error, continue-after-failure, fail-fast, list, group, and exit semantics tests).
- `python3 tools/check_storage_sql_ownership.py` → passed.
- `python3 tools/check_architecture.py` → passed.
- `cargo run -q -p loom-validator -- --help` → prints documented usage and exit semantics (exit `0`).
- `cargo run -q -p loom-validator -- --list` → `available scenarios (0):` for bootstrap (exit `0`).
- `cargo run -q -p loom-validator` → `loom-validator: 0 scenario(s) selected` + summary line (exit `0`).
- `cargo run -q -p loom-validator -- CV-001` → `error: unknown scenario id(s): CV-001` (exit `2`, no fake failure).
- Selection determinism verified via `runner::tests::deterministic_execution_ordering` and `multi_selection_is_sorted_and_deduped`.
- Unknown-ID runner error verified via `runner::tests::unknown_ids_return_runner_error` and `cli::tests::unknown_ids_return_runner_error_exit_2`.
- Continue-after-failure verified via `runner::tests::failing_scenario_does_not_prevent_later` and `cli::tests::failing_scenario_continues_in_normal_mode`.
- Exit semantics distinct verified via `cli::tests::exit_semantics_are_distinct` and documented in `cli.rs` and `main.rs`.
- Reviewer独立验收 `01a034e3-74b4-7984-b93f-5e604cd146dd`（PR #269 `acecd7f`）对 AC-1..AC-8 全量通过，复现 56 passed / fmt/clippy/check 0 / 实测 exit 符合文档。
- PR #269 已于 2026-08-24T17:53:17Z squash 合并至 `main`，merge SHA `f84fd1f387ba2da43f28c489071c1013549b8217`，CI `Rust checks`/`PostgreSQL 18 persistence contract` 均 pass，GitHub Issue #255 已自动关闭。

Acceptance 已由 Reviewer 确认并随合并完成。
