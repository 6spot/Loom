---
task: VALR-T06
issue: 311
status: in_progress
depends_on: [309, 307]
created_at: 2026-08-26
started_at: 2026-08-26
completed_at:
completion_pr:
merge_sha:
---

# VALR-T06 — Wire required-live policy to trusted PostgreSQL evidence

Make required-live gating enforce what its name claims: the gate passes only when every selected result satisfies strict policy **and** at least one trusted controlled `PostgreSQL` result passes.

## Goal

Wire `required-live` end-to-end into CLI exit semantics so ambient `LOOM_TEST_POSTGRES_URL` cannot fake `PostgreSQL` evidence and every non-`Pass` selected outcome (`Fail`, `Skipped`, `Unavailable`) fails the gate.

## Current defect

The report layer had a `required-live` policy concept (`ValidationPolicy::required_live`) and correct gate evaluation, but CLI exit behavior did not fully enforce it (`--required-live` flag missing, `execute_cli`/`run_from_args` only checked `strict`) and the production harness already correctly reported `External` for generic endpoints — the wiring from single-pass execution through policy evaluation to exit status was absent.

## Scope

Allowed:
- Validator CLI policy selection (`apps/loom-validator/src/cli.rs`);
- Report/gate evaluation consumption (`apps/loom-validator/src/reports.rs` and `apps/loom-validator/src/backend.rs` via `VALR-T04` model);
- Focused CLI/report and CLI-subprocess tests;
- This task's ledger record.

Forbidden:
- Do not redefine trusted backend construction; consume `VALR-T04`'s `BackendEvidence`/`BackendHarness` model;
- Do not change restart semantics; `VALR-T05` owns `RestartCapability`;
- Do not add capability scenarios;
- Do not add storage-implementation introspection API.

## Implementation

1. Extended `CliArgs` in `apps/loom-validator/src/cli.rs:45` with `required_live: bool` and `is_required_live()` accessor; added `--required-live` parsing in `parse_args` (`cli.rs:148`) alongside `--strict`/`--fail-fast`.
2. Updated `help_text` (`cli.rs:240`) and module-level exit-semantics docs to document `--required-live` as strict plus at least one passing result with trusted controlled `PostgreSQL` evidence; exit 1 now describes `strict` or `required-live` gate failure, exit 2 remains runner/config error.
3. Extended `CliAction::Run` (`cli.rs:288`) to carry `required_live` for test introspection; `decide_action` propagates it.
4. Wired policy selection in both execution paths to use single-pass execution then policy gate:
   - `execute_cli` (`cli.rs:482`): `if required_live { required_live() } else if strict { strict() } else { best_effort() }` via `runner.run_selected(...).with_policy(policy)`; exit is `1` iff `(strict || required_live) && !report.gate_passes()`.
   - `run_from_args` (`cli.rs:580`, `cli.rs:620`, `cli.rs:681`): `BackendHarness` policy set analogously before `run_with_harness_selected`; same gate check after single-pass harness execution (`run_with_harness_selected` is `VALR-T01` single-pass authority, no replay). Gate evaluation remains in `ValidationReport::gate_passes` (`reports.rs:592`) which already enforces `!results.is_empty() && !any !is_pass && (required_live => backend_evidence == PostgreSQL && any finding.backend.evidence == PostgreSQL && is_pass)`.
5. Preserved `VALR-T04` evidence authority: `run_from_args` generic endpoint remains `BackendEvidence::External` (`cli.rs:589`) and never consults `LOOM_TEST_POSTGRES_URL`; controlled `InMemory`/`PostgreSQL` evidence only via explicit `BackendContext::with_backend_kind` / `BackendHarness::connect(kind)` construction. Ambient PG URL cannot upgrade external evidence.
6. Preserved `VALR-T03` selection error semantics: `resolve_with_groups` `RunnerError::UnknownScenarioIds`/`UnknownGroups`/`EmptySelection`/`InvalidSelection` all map to `EXIT_RUNNER_ERROR` (2) before execution; `required-live` does not swallow selection errors.
7. Preserved `VALR-T01` single-pass and `VALR-T02` strict/fail-fast separation; `fail_fast` still only controls early stop, `required_live` does not imply `fail_fast`.

## Required tests

Focused coverage proves (all via `cargo test -p loom-validator` and subprocess `required_live` gate):

- `required-live + all Pass controlled PostgreSQL => exit 0` (`cli::tests::required_live_all_pass_postgresql_passes` via `BackendContext::PostgreSQL` + `passing_aware`);
- `required-live + all Pass external endpoint => exit 1` (`required_live_all_pass_external_fails`);
- `required-live + all Pass controlled InMemory only => exit 1` (`required_live_all_pass_inmemory_fails`);
- `required-live + controlled PostgreSQL + one Skipped => exit 1` (`required_live_postgresql_with_skipped_fails`);
- `required-live + controlled PostgreSQL + Unavailable => exit 1` (`required_live_postgresql_with_unavailable_fails`);
- `required-live + controlled PostgreSQL + Fail => exit 1` (`required_live_postgresql_with_fail_fails`);
- `ambient LOOM_TEST_POSTGRES_URL cannot upgrade external evidence` (`ambient_postgres_url_cannot_upgrade_external_required_live` unit + `BackendHarness` external check + `tests/required_live.rs::required_live_with_external_endpoint_fails_even_with_pg_url` subprocess with valid and malformed PG URL);
- `selection errors remain exit 2` (`required_live_selection_error_remains_exit_2`, `required_live_unknown_group_remains_exit_2`, plus subprocess `required_live_selection_error_remains_exit_2` and `required_live_with_unknown_group_remains_exit_2`);
- `single-pass preserved under required-live` (`required_live_single_pass_is_preserved` counter proof);
- `harness external fails required-live even with PG URL` (`required_live_harness_external_fails_even_with_pg_url`);
- `InMemory all Pass is not a required-live pass` and `required-live rejects any non-pass with PostgreSQL evidence` (`reports::tests::inmemory_all_pass_is_not_a_required_live_pass`, `required_live_rejects_any_non_pass_even_with_postgres_evidence`);
- Existing `strict` and `backend_evidence` regressions remain green.

Added in `apps/loom-validator/src/cli.rs`:
- `parse_required_live_flag`
- `required_live_all_pass_postgresql_passes`
- `required_live_all_pass_external_fails`
- `required_live_all_pass_inmemory_fails`
- `required_live_postgresql_with_skipped_fails`
- `required_live_postgresql_with_unavailable_fails`
- `required_live_postgresql_with_fail_fails`
- `ambient_postgres_url_cannot_upgrade_external_required_live`
- `required_live_selection_error_remains_exit_2`
- `required_live_unknown_group_remains_exit_2`
- `required_live_single_pass_is_preserved`
- `required_live_harness_external_fails_even_with_pg_url`
- `help_text_documents_required_live`

Added in `apps/loom-validator/src/reports.rs`:
- `inmemory_all_pass_is_not_a_required_live_pass`
- `required_live_rejects_any_non_pass_even_with_postgres_evidence`

Added in `apps/loom-validator/tests/required_live.rs`:
- `required_live_with_external_endpoint_fails_even_with_pg_url` (valid + malformed PG URL, report `backend_evidence == external`, `required_live == true`, exit 1)
- `required_live_selection_error_remains_exit_2` (exit 2, `runner_config_failure`)
- `required_live_with_unknown_group_remains_exit_2` (exit 2)

## Acceptance

- [x] Required-live is wired end-to-end into CLI exit semantics (single-pass `run_selected`/`run_with_harness_selected` → `ValidationPolicy::required_live` → `gate_passes` → exit 1/0, selection errors → exit 2).
- [x] Only trusted controlled `PostgreSQL` evidence satisfies the live requirement (`BackendEvidence::PostgreSQL` via explicit `BackendContext`/`BackendHarness` kind; `External`/`InMemory` and ambient `LOOM_TEST_POSTGRES_URL` never satisfy).
- [x] Strict non-pass outcomes cannot false-green required-live (`Fail`/`Skipped`/`Unavailable` all make `gate_passes` false).
- [x] Regression tests cover fake-PG and no-PG cases (subprocess external + PG URL, report `backend_evidence_trusted` and policy fields).
- [ ] Review and CI are complete before marking the task completed.

## Verification Evidence

- `cargo fmt --all -- --check` → passed
- `cargo check -p loom-validator --all-targets --all-features` → passed
- `cargo clippy -p loom-validator --all-targets --all-features -- -D warnings` → passed
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` → passed
- `cargo test -p loom-validator --lib --all-features` → 150 passed, 0 failed (includes 13 new `required-live` CLI/report tests)
- `bash tools/test.sh -p loom-validator --all-features` → passed (150 lib + 1 backend_evidence + 3 required_live + 6 restart_evidence + 3 lifecycle + 4 replay_fork + 2 runtime_authority)
- `cargo test -p loom-validator --test required_live --all-features` → 3 passed (external + PG URL, selection error, unknown group)
- `cargo test -p loom-validator --test backend_evidence --all-features` → 1 passed (generic endpoint never infers postgres)
- `python3 tools/check_architecture.py` → passed (Loom architecture dependency policy: OK, storage SQL ownership check passed)
- `python3 tools/check_storage_sql_ownership.py` → passed
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert/stage-1 --check --format json` → `exit 1`, `valid=false`, `violations=[VALR-T06 dependency 309 is in_progress]` (expected: `VALR-T06` 仍 `in_progress` 且被 `VALR-T03` 阻塞于同一 PR #338，`ready=[VALR-T03]`，`blocked=[VALR-T06]`，无 completion evidence 缺失；`VALR-T02` 已为 `completed`（PR #336, `13f6adfe860dcbbb3e414208d7e49361a4b52220`），`VALR-T03` `in_progress` 待合并，`307` 已完成)

## Progress Log

- 2026-08-26 — Added `--required-live` flag, `ValidationPolicy::required_live` wiring through `execute_cli` and `run_from_args` single-pass paths, and strict-plus-PostgreSQL gate verification; preserved `VALR-T04` external evidence authority and `VALR-T03` selection-error exit 2 semantics.
- 2026-08-26 — Added focused unit/report tests for external/InMemory vs PostgreSQL, Skipped/Unavailable/Fail rejection, ambient PG non-upgrade, single-pass preservation, and subprocess `required_live` gate (external + PG URL, malformed PG, selection errors); updated help text and docs.
- 2026-08-26 — Ran `cargo fmt`, `cargo clippy`, `bash tools/test.sh -p loom-validator --all-features`, and `validator_ready` checks; recorded ledger.
- 2026-08-26 — Rework D-1: `t02-strict-policy` 按 PR #336 补 `completed` 证据（`13f6adfe860dcbbb3e414208d7e49361a4b52220`），`t03-selection-integrity` 回退为 `in_progress` 待 PR #338 合并（已集成 `4e4cd92`），`t06-required-live` 仅修正 `validator_ready` 验证记录；`apps/loom-validator` 运行时语义未动。复核 `validator_ready --check`：`ready=[VALR-T03]`，`blocked=[VALR-T06]`，`valid=false` 因 `VALR-T06` 被同 PR 内 `VALR-T03` 阻塞（`dependency 309`），但无 `completion_pr`/`merge_sha` 缺失等 completion evidence 违规，`VALR-T02` 已 `completed`。
