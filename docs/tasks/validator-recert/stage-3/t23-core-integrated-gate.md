# VALR-T23 — Core V0 integrated gate evidence

## Run identity and candidate discipline

- Run date: 2026-08-27 (Asia/Shanghai).
- Isolated checkout: `/home/opc/multica_workspaces/me-ee43a71168f9/me-299-b5959bbd1fe3/workdir/Loom`.
- Branch: `agent/executor/b5959bbd1fe3`.
- Production candidate/base recorded before evidence collection: `34fc8efa77cf61d8a9261eaec575bbe111615618`.
- Initial `git status --short --branch`: `## agent/executor/b5959bbd1fe3` (clean).
- Initial `git rev-parse HEAD`: `34fc8efa77cf61d8a9261eaec575bbe111615618`.
- The only source change in this evidence descendant is this ledger. No production, Runtime, Storage, Validator scenario/test source, schema/migration, CI/workflow, or other ledger file was changed.
- Final disposition: **T23 core integrated gate PASS; final V0 certification NOT CLAIMED.** The initial required T20 live matrix failure, the D-001 fresh-database rerun, and all inherited T22 capability gaps remain explicitly recorded below. T23 is ready for independent review; this ledger does not claim final V0 certification.
- Race protocol: closed; this ledger adds no persistence, claim/release, retry, checkpoint, marker, or concurrency state.

## AC mapping

- AC-1: exact candidate, isolated branch/worktree, and clean pre-evidence state are recorded above; all evidence below targets that candidate.
- AC-2: the T22 ten-domain manifest was used as the checklist; every CV and static/build row is listed below with its command and named test/job.
- AC-3: PG-required commands used `LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_control` or the repository wrapper default. The live service was `pgvector/pgvector:0.8.6-pg18`, PostgreSQL `18.6`, bound to `127.0.0.1:15432`; fixtures created isolated migrated child databases. No skipped or unavailable result is reported as a PG pass.
- AC-4: aggregate and row-level failures/skips/gaps are preserved below; the CV-016 failure is not downgraded.
- AC-5: this is the reviewable evidence ledger only. Final V0 certification remains owned by T25.

## Required Validator/core matrix

All focused Validator commands below were run with the repository `bash tools/test.sh` wrapper, which started/reused the repository-managed PG18 service and exported its control URL. `PASS` means the named test binary assertions executed and passed; it does not convert an intentionally unavailable/gap capability into a capability pass.

| Row | Exact command | Named test / actual result | Candidate / PG or restart fact |
| --- | --- | --- | --- |
| CV-001 | `bash tools/test.sh -p loom-validator --test lifecycle -- --test-threads=1` | `lifecycle::cv001_to_cv003_pass_on_real_in_memory`; `lifecycle::cv001_to_cv004_pass_on_live_postgres` — PASS | `34fc8efa`; live PG path executed |
| CV-002 | same lifecycle command | `lifecycle::cv001_to_cv003_pass_on_real_in_memory` — PASS | `34fc8efa`; public Action/read path |
| CV-003 | same lifecycle command | `lifecycle::cv001_to_cv004_pass_on_live_postgres` — PASS | `34fc8efa`; controlled PG boundary path |
| CV-004 | same lifecycle command | `lifecycle::cv001_to_cv004_pass_on_live_postgres` — PASS | `34fc8efa`; controlled PG boundary restart |
| CV-005 | `bash tools/test.sh -p loom-validator --test replay_fork -- --test-threads=1` | `replay_fork::cv005_to_cv008_pass_on_real_in_memory_service`; `::cv005_to_cv008_pass_on_live_postgres_service_when_configured` — PASS | `34fc8efa`; PG live path executed |
| CV-006 | same replay_fork command | `cv005_to_cv008_*` — PASS | `34fc8efa`; fork identity assertions executed |
| CV-007 | same replay_fork command | `cv005_to_cv008_*` — PASS | `34fc8efa`; child/parent isolation assertions executed |
| CV-008 | same replay_fork command | `cv005_to_cv008_*` — PASS | `34fc8efa`; ancestry/historical fork assertions executed |
| CV-009 | same replay_fork command | `replay_fork::cv009_postgres_restart_survives_real_boundary_rebuild_when_configured` — PASS | `34fc8efa`; controlled PG boundary rebuild |
| CV-010 | `bash tools/test.sh -p loom-validator --test runtime_authority -- --test-threads=1` | `runtime_authority::cv010_rejects_partial_binding_without_rewriting_it` — PASS | `34fc8efa`; fail-closed negative path |
| CV-011 | same runtime_authority command | `runtime_authority::cv011_rejects_missing_active_revision` — PASS | `34fc8efa`; fail-closed negative path |
| CV-012 | `bash tools/test.sh -p loom-validator --test world_binding -- --test-threads=1` | `world_binding::cv012_binding_immutability_passes_on_real_in_memory`; `::cv012_binding_immutability_passes_on_live_postgres_when_configured` — PASS | `34fc8efa`; PG path executed |
| CV-013 | same world_binding command | `world_binding::cv013_compatible_revision_permits_action_passes_on_real_in_memory`; `::cv013_compatible_revision_permits_action_passes_on_live_postgres_when_configured` — PASS | `34fc8efa`; PG path executed |
| CV-014 | T20 command below | `postgres_live_gate::t20_live_gate_runs_exactly_ten_structured_required_live_rows` returned CV-014 `Pass` | `34fc8efa`; controlled PG restart retained Binding/history |
| CV-015 | `bash tools/test.sh -p loom-validator --test action_ingress -- --test-threads=1` | `action_ingress::cv015_accepted_action_commits_via_in_memory_server`; `::cv015_accepted_action_commits_via_pg_with_restart_if_available` — PASS | `34fc8efa`; PG restart path executed |
| CV-016 | T20 command below | T20 structured row returned `Fail`: first submit of `t11.cv016.key1` got `IdempotencyConflict`; existing ingress `ingress-cv016-1`, existing fingerprint `87504a5a4f8ba73b`, submitted fingerprint varied (`a3c8ebf2d9ef6fda` / `bde25551caca8cf4`) | `34fc8efa`; repository-managed PG18 persistent control volume; required failure, not a pass |
| CV-017 | `bash tools/test.sh -p loom-validator --test action_ingress -- --test-threads=1` | `action_ingress::cv017_blocked_is_unavailable_everywhere`; `::cv017_execute_never_adds_fault_injection_seam` — PASS as gap/scaffold assertions | `34fc8efa`; manifest capability status remains GAP: no controlled public fault-injection seam |
| CV-018 | `bash tools/test.sh -p loom-validator --test scheduler -- --test-threads=1` | `scheduler::scheduler_cv020_blocked_gaps_have_no_descriptor_or_pass` — PASS as gap assertion; no CV-018 executable descriptor | `34fc8efa`; manifest capability status remains GAP: no public generic schedule/claim surface |
| CV-019 | same scheduler command | `scheduler_cv020_blocked_gaps_have_no_descriptor_or_pass` — PASS as gap assertion; no CV-019 executable descriptor | `34fc8efa`; manifest capability status remains GAP: no public claim/fence injection surface |
| CV-020 | same scheduler command | `scheduler::cv020_independent_timelines_pass_on_real_in_memory_service`; `::cv020_independent_timelines_pass_on_live_postgres_service_when_configured` — PASS | `34fc8efa`; PG path executed |
| CV-021 | `bash tools/test.sh -p loom-validator --test world_time -- --test-threads=1` | `world_time::cv021_explicit_advance_passes_on_real_in_memory`; `::cv021_explicit_advance_passes_on_live_postgres` — PASS | `34fc8efa`; PG CAS path executed |
| CV-022 | T20 command below | T20 structured row `Pass`; due Work rejected time advance and restart verified | `34fc8efa`; controlled PG restart |
| CV-023 | T20 command below | T20 structured row `Pass`; chronology/logical order reconstructed identically after controlled restart | `34fc8efa`; controlled PG restart |
| CV-024 | `bash tools/test.sh -p loom-validator --test world_time -- --test-threads=1` | `world_time::cv024_reaction_atomicity_passes_after_controlled_in_memory_restart`; `::cv024_reaction_atomicity_passes_on_live_postgres` — PASS | `34fc8efa`; PG path executed |
| CV-025 | `bash tools/test.sh -p loom-validator --test query_catalog -- --test-threads=1` | `query_catalog::cv025_history_trajectory_isolation_on_in_memory`; `::cv025_to_cv027_postgres_when_available` — PASS | `34fc8efa`; PG path executed |
| CV-026 | same query_catalog command | `query_catalog::cv026_causal_query_isolation_on_in_memory`; `::cv025_to_cv027_postgres_when_available` — PASS | `34fc8efa`; branch/world isolation assertions |
| CV-027 | same query_catalog command | `query_catalog::cv027_world_scoped_catalog_positive_on_in_memory`; `::cv027_no_active_revision_is_not_permissive`; `::catalog_authority_does_not_use_global_fallback_on_controlled_in_memory` — PASS | `34fc8efa`; public catalog authority assertions |
| CV-028 | `bash tools/test.sh -p loom-validator --test semantic_blob -- --test-threads=1` | `semantic_blob::cv028_and_cv029_are_blocked_gaps_on_in_memory_and_pg`; `::cv028_cv029_do_not_enlarge_central_registry_even_when_executed` — PASS as gap/scaffold assertions | `34fc8efa`; manifest capability status remains GAP: no public SemanticService projection API |
| CV-029 | same semantic_blob command | `cv028_and_cv029_are_blocked_gaps_on_in_memory_and_pg` — PASS as gap assertion | `34fc8efa`; manifest capability status remains GAP: no public blob/reference operation |
| CV-030 | T20 command below | T20 structured row `Pass`; pinned TimelineVersion remained stable across head mutation, fork, and controlled PG restart | `34fc8efa`; controlled PG boundary restart |
| CV-031 | T20 command below | T20 structured row `Pass`; Event→Session→R1 linkage retained across activation/restart | `34fc8efa`; controlled PG boundary restart |
| CV-032 | T20 command below | T20 structured row `Pass`; new Session used R2 while R1 history remained unchanged across restart | `34fc8efa`; controlled PG boundary restart |
| CV-033 | T20 command below | T20 structured row `Pass`; implementation/read/call/entropy evidence retained | `34fc8efa`; controlled PG boundary restart |
| CV-034 | `bash tools/test.sh -p loom-validator --test agency -- --test-threads=1` | `agency::agency_suite_scaffold_is_non_registering_and_disjoint` — PASS as scaffold assertion; no executable CV-034 | `34fc8efa`; manifest capability status remains GAP: no public Agency Wake execution seam |
| CV-035 | same agency command | same non-registering scaffold — PASS as gap assertion; no executable CV-035 | `34fc8efa`; manifest capability status remains GAP: no public Decision injection/Act seam |
| CV-036 | same agency command | same non-registering scaffold — PASS as gap assertion; no executable CV-036 | `34fc8efa`; manifest capability status remains GAP: no public Rejected observation |
| CV-037 | same agency command | same non-registering scaffold — PASS as gap assertion; no executable CV-037 | `34fc8efa`; manifest capability status remains GAP: no public concurrent claim/fence surface |
| CV-038 | `bash tools/test.sh -p loom-validator --test change_feed -- --test-threads=1` | `change_feed::cv038_passes_on_real_in_memory_via_formal_subscription`; `::cv038_to_cv040_pass_on_live_postgres_with_controlled_restart` — PASS | `34fc8efa`; controlled PG restart path |
| CV-039 | T20 command below | T20 structured row `Pass`; valid cursor resumed at documented boundary after restart | `34fc8efa`; controlled PG restart |
| CV-040 | T20 command below | T20 structured row `Pass`; disconnect/reconnect and EventId dedup preserved authoritative history | `34fc8efa`; controlled PG restart |

## T20 required-live matrix

- Exact command: `bash tools/validator-pg18-gate.sh`.
- Service preparation: `bash tools/postgres-test.sh up` reported healthy container `loom-postgres-test-1`, image `pgvector/pgvector:0.8.6-pg18`, port `127.0.0.1:15432`.
- Database fact: `select version()` returned PostgreSQL `18.6` on `aarch64-unknown-linux-gnu`.
- Result: **FAIL, exit 101**. The test executed both matrix tests; `t20_required_live_policy_is_fail_closed_for_zero_nonpass_and_ambient_evidence` passed, while `t20_live_gate_runs_exactly_ten_structured_required_live_rows` failed because the ten-row required-live report contained CV-016 `Fail`.
- Structured rows actually executed: CV-014 `Pass`, CV-016 `Fail`, CV-022 `Pass`, CV-023 `Pass`, CV-030 `Pass`, CV-031 `Pass`, CV-032 `Pass`, CV-033 `Pass`, CV-039 `Pass`, CV-040 `Pass`.
- CV-016 exact failure: `first submit expected Accepted, got IdempotencyConflict { idempotency_key: t11.cv016.key1, existing_ingress_id: ingress-cv016-1, existing_request_fingerprint: 87504a5a4f8ba73b, submitted_request_fingerprint: a3c8ebf2d9ef6fda }`. A second rerun produced the same class with submitted fingerprint `bde25551caca8cf4`.
- The required report did not produce a certifying artifact because the matrix assertion failed; no absent artifact is treated as pass.

## PostgreSQL 18 CI contract commands

These exact CI commands were run with `LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_control` against the repository-managed PG18 service. Every command below returned exit 0 and every named test executed with zero failures/skips:

| Job/command | Executed result |
| --- | --- |
| `cargo test -p loom-storage --test postgres_schema -- --nocapture` | `postgres_18_schema_starts_empty_runs_migrations_and_enforces_constraints`: 1 passed |
| `cargo test -p loom-storage --test postgres_lifecycle -- --nocapture` | 4 passed, including atomic lifecycle, binding restart, template birth |
| `cargo test -p loom-storage --test postgres_lifecycle postgres_18_template_birth_is_atomic_and_snapshots_binding -- --nocapture` | 1 passed, 3 filtered |
| `cargo test -p loom-storage --test postgres_vertical -- --nocapture` | 1 passed |
| `cargo test -p loom-storage --test postgres_read -- --nocapture` | 1 passed |
| `cargo test -p loom-storage --test postgres_commit -- --nocapture` | 9 passed |
| `cargo test -p loom-storage --test postgres_work -- --nocapture` | 12 passed |
| `cargo test -p loom-storage --test postgres_work_stale_completion -- --nocapture` | 1 passed |
| `cargo test -p loom-storage --test postgres_restart_resume -- --nocapture` | 1 passed |
| `cargo test -p loom-storage --test postgres_revision -- --nocapture` | 2 passed |
| `cargo test -p loom-validator --test lifecycle -- --nocapture` | 3 passed |
| `cargo test -p loom-validator --test replay_fork -- --nocapture` | 4 passed |

These PG contract passes are complementary evidence and do not override the failed required-live CV-016 matrix row or the manifest capability gaps.

## Static, dependency, build, client, SSE, and CLI evidence

| Required check | Exact command / named job | Result |
| --- | --- | --- |
| Architecture dependency DAG | `python3 tools/check_architecture.py` / `Rust checks / Architecture policy` | PASS: `Loom architecture dependency policy: OK` |
| Storage SQL ownership | `python3 tools/check_storage_sql_ownership.py` | PASS: `storage SQL ownership check passed` |
| Dependency/security | `cargo deny check advisories bans licenses sources` / `Rust checks / Dependency and security policy` | PASS: advisories, bans, licenses, sources all ok |
| Format | `cargo fmt --all -- --check` / `Format` | PASS |
| Check | `cargo check --workspace --all-targets --all-features` / `Check` | PASS; workspace finished successfully |
| Strict clippy | `cargo clippy --workspace --all-targets --all-features -- -D warnings` / `Clippy` | PASS; workspace finished successfully |
| Rustdoc | `RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps` / `Rustdoc` | PASS; all workspace crates documented |
| Workspace tests | `bash tools/test.sh --workspace --all-features` / `Test` | **FAIL, exit 101** at `postgres_live_gate::t20_live_gate_runs_exactly_ten_structured_required_live_rows`; all preceding executed tests and the first T20 policy test are retained as evidence, with CV-016 failure shown above |
| Validator focus suites | `bash tools/test.sh -p loom-validator --test world_binding/runtime_authority/action_ingress/lifecycle/scheduler/world_time/query_catalog/semantic_blob/replay_fork/agency/change_feed -- --test-threads=1` (each exact command was run separately) | PASS counts: 10 / 2 / 9 / 3 / 4 / 10 / 7 / 7 / 4 / 1 / 7; no skipped tests. Gap suites only assert their documented non-registering/unavailable contract |
| Formal client/SSE/unit boundary | Included in workspace tests; named `loom_client::tests::typed_boundary_errors_preserve_public_category`, `::sse_change_frames_round_trip_as_a_resumable_page`, `loom_api::tests::focused_services_form_one_public_world_api`, `loom_boundary` SSE/transport tests | PASS in workspace: client 4, API 7, boundary 10, CLI unit/integration 9 |
| CLI required-live boundary | `LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_control cargo run -q -p loom-validator -- --all --strict --required-live --json target/validator/t23-validator-all-required-live.json` | **FAIL, exit 1**: `31 total, 0 pass, 2 fail, 16 skipped, 13 unavailable`; endpoint was the default external `loom-client` at `http://127.0.0.1:8080/`, with CV-023/CV-024 explicitly failing reconnect-only restart and other unavailable/skip results preserved in machine evidence |
| Validator ledger check | `python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json` | **FAIL / invalid ledger graph**: `valid:false`; T17 explicit architecture blocker and T19/T20/T21 in-progress dependency chain are reported |

The repository's `python3 tools/test_validator_ready.py`, `python3 tools/validator_ready.py --check --format json`, and Stage-1 `python3 tools/validator_ready.py --root docs/tasks/validator-recert/stage-1 --check --format json` checks also executed successfully; they validate their respective ledger fixtures and do not certify this failed T23 gate.

## Final diff and handoff

- Required source diff: this file only (`docs/tasks/validator-recert/stage-3/t23-core-integrated-gate.md`).
- Generated workspace artifacts (`target/`) are ignored and are not part of the source diff.
- No PR was created by Executor.
- Final V0 certification is not claimed here. The initial CV-016 failure is preserved as historical non-certifying evidence; the D-001 fresh rerun passes it. The remaining final-certification scope is the explicit T22 gaps CV-017..CV-019, CV-028..CV-029, and CV-034..CV-037.

## D-001 clean-database rerun

- Fixed candidate/base/HEAD for every rerun: `34fc8efa77cf61d8a9261eaec575bbe111615618`.
- Fresh database: `loom_t23_certification`, URL `postgresql://loom:loom@127.0.0.1:15432/loom_t23_certification`. It was created only on the repository-managed `loom-postgres-test-1` service with `pgvector/pgvector:0.8.6-pg18`; `select version()` reported PostgreSQL `18.6` (`aarch64-unknown-linux-gnu`). The sibling `loom_t24_certification` database was not dropped, altered, or queried for test data; final database enumeration showed `loom_control`, `loom_t23_certification`, and `loom_t24_certification`.
- The fresh DB was reset only by the explicit `DROP DATABASE loom_t23_certification WITH (FORCE); CREATE DATABASE loom_t23_certification OWNER loom;` command, before the final workspace and T20 runs. This reset targeted only the T23 database and did not interrupt T24.
- A first workspace attempt on the fresh DB failed before tests at the linker with `No space left on device` after generated target growth; it is recorded as an environment `FAIL/NOT_RUN`, not as validation evidence. Only this checkout's generated `target/` was cleaned. The successful retry used `CARGO_INCREMENTAL=0 CARGO_BUILD_JOBS=2` and the same explicit fresh URL.

### Fresh workspace and Validator focus

- `LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_t23_certification CARGO_INCREMENTAL=0 CARGO_BUILD_JOBS=2 bash tools/test.sh --workspace --all-features` — **PASS, exit 0**. Required tests executed and passed: `loom_validator` unit 165; `action_ingress` 9; `agency` 1; `authority_gate` 7; `backend_evidence` 1; `change_feed` 7; `lifecycle` 3; `postgres_live_gate` 2 (including T20 10/10); `provenance` 9; `query_catalog` 7; `replay_fork` 4; `required_live` 3; `restart_evidence` 6; `runtime_authority` 2; `scheduler` 4; `semantic_blob` 7; `world_binding` 10; `world_time` 10. Relevant workspace storage binaries also passed: `postgres_schema` 1, `postgres_lifecycle` 4, `postgres_vertical` 1, `postgres_read` 1, `postgres_commit` 9, `postgres_work` 12, `postgres_work_stale_completion` 1, `postgres_restart_resume` 1, `postgres_revision` 2, and `semantic_projection` 3. No required test was skipped or ignored; the auxiliary `query_catalog_causal_fixture` ran 0 tests and is not treated as evidence.
- Fresh Validator focus commands, each run separately with the same explicit URL and `--test-threads=1`, all **PASS** with zero failures/skips: `bash tools/test.sh -p loom-validator --test world_binding -- --test-threads=1` (10); `runtime_authority` (2); `action_ingress` (9); `lifecycle` (3); `scheduler` (4); `world_time` (10); `query_catalog` (7); `semantic_blob` (7); `replay_fork` (4); `agency` (1); `change_feed` (7); `provenance` (9). Gap rows CV-017..CV-019, CV-028..CV-029, and CV-034..CV-037 remain gap/scaffold assertions, not capability passes.

The remaining exact focus commands were:

```text
bash tools/test.sh -p loom-validator --test runtime_authority -- --test-threads=1
bash tools/test.sh -p loom-validator --test action_ingress -- --test-threads=1
bash tools/test.sh -p loom-validator --test lifecycle -- --test-threads=1
bash tools/test.sh -p loom-validator --test scheduler -- --test-threads=1
bash tools/test.sh -p loom-validator --test world_time -- --test-threads=1
bash tools/test.sh -p loom-validator --test query_catalog -- --test-threads=1
bash tools/test.sh -p loom-validator --test semantic_blob -- --test-threads=1
bash tools/test.sh -p loom-validator --test replay_fork -- --test-threads=1
bash tools/test.sh -p loom-validator --test agency -- --test-threads=1
bash tools/test.sh -p loom-validator --test change_feed -- --test-threads=1
bash tools/test.sh -p loom-validator --test provenance -- --test-threads=1
```

### Fresh PostgreSQL contract

With `LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_t23_certification`, each exact CI-listed command returned exit 0 and the named tests executed without failure or skip: `cargo test -p loom-storage --test postgres_schema -- --nocapture` (1); `postgres_lifecycle -- --nocapture` (4); `postgres_lifecycle postgres_18_template_birth_is_atomic_and_snapshots_binding -- --nocapture` (1 passed, 3 filtered); `postgres_vertical -- --nocapture` (1); `postgres_read -- --nocapture` (1); `postgres_commit -- --nocapture` (9); `postgres_work -- --nocapture` (12); `postgres_work_stale_completion -- --nocapture` (1); `postgres_restart_resume -- --nocapture` (1); `postgres_revision -- --nocapture` (2); `cargo test -p loom-validator --test lifecycle -- --nocapture` (3); and `replay_fork -- --nocapture` (4). All were run against the fresh T23 database on candidate `34fc8efa`.

### Fresh T20 required-live rerun

- Exact command: `LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_t23_certification LOOM_T20_REPORT_PATH="$PWD/target/validator/t23-fresh-pg18-live-gate.json" CARGO_INCREMENTAL=0 CARGO_BUILD_JOBS=2 bash tools/validator-pg18-gate.sh`.
- Final run was made after resetting only `loom_t23_certification` to an empty database. Result: **PASS, exit 0**; `postgres_live_gate` ran 2 tests, both passed. Machine report `target/validator/t23-fresh-pg18-live-gate.json` has `gate_passes: true`, `backend_evidence: postgresql`, `backend_evidence_trusted: true`, and exactly `10 total, 10 pass, 0 fail, 0 skipped, 0 unavailable`.
- Fresh structured rows: CV-014 `Pass`; CV-016 `Pass` (Accepted then Deduplicated, Completed Committed with one EventRef/history/facet, survived controlled boundary restart); CV-022 `Pass`; CV-023 `Pass`; CV-030 `Pass`; CV-031 `Pass`; CV-032 `Pass`; CV-033 `Pass`; CV-039 `Pass`; CV-040 `Pass`.
- An earlier T20 attempt after the fresh focus/contract commands was intentionally retained as a non-certifying failure: CV-016 saw an existing `t11.cv016.key1` record and returned `IdempotencyConflict`. This exposed test-state contamination in that already-used database; it was not relabeled or overwritten. The final empty-database rerun above is the only fresh T20 evidence used for the row-level result.

### D-001 conclusion

- D-001 confirms the T20 CV-016 behavior on an independently reset, repository-controlled PostgreSQL 18 database. The original `loom_control` CV-016 failure remains historical non-certifying evidence above and is not converted to PASS.
- The T22 capability gaps remain unchanged: CV-017..CV-019, CV-028..CV-029, and CV-034..CV-037 have no required public execution surfaces. They are parallel Validator/final-certification scope and are not reclassified as PASS. Therefore the final disposition is **T23 core integrated gate PASS; final V0 certification NOT CLAIMED**.
- Final source scope remains this ledger only. `git status --short --branch` shows branch `agent/executor/b5959bbd1fe3` at candidate `34fc8efa` with only this untracked ledger; generated `target/` artifacts are ignored and are not source diff.

## D-002 final disposition and AC mapping

- **AC-1 candidate integrity: PASS.** The isolated worktree, branch, and exact candidate/base/HEAD `34fc8efa77cf61d8a9261eaec575bbe111615618` are recorded; the evidence descendant changes this ledger only.
- **AC-2 current required executable/core evidence: PASS.** The fresh `loom_t23_certification` workspace, Validator focus, CI-listed PostgreSQL contract, and T20 required-live evidence are current and passing. Inherited T22 capability gaps CV-017..CV-019, CV-028..CV-029, and CV-034..CV-037 remain explicit gap rows and are not claimed exercised or passed.
- **AC-3 real PG18 execution: PASS.** Fresh certifying evidence ran against repository-controlled PostgreSQL `18.6` on `loom_t23_certification`; T20 produced 10/10 required-live rows PASS with trusted PostgreSQL evidence and controlled boundary restart facts.
- **AC-4 no hidden failure/skip: PASS.** The original reused-`loom_control` CV-016 failure, later same-database contamination observation, linker environment failure, filtered/non-required zero-test observation, CLI external failure, and ledger-check failure remain recorded as historical/non-certifying evidence. No required fresh failure or skip was hidden.
- **AC-5 reviewable ledger: PASS.** This file preserves the complete candidate discipline, row-level gaps, historical observations, fresh commands/results, boundary/client/SSE/CLI evidence, and current disposition.
- T23 completion still requires independent Reviewer approval, finished required CI, final merge gate, PR merge, and Done confirmation. Final V0 certification remains unclaimed until the manifest gaps are resolved or accepted by the final decision owner.

## Current-main rerun on `4efb1d346c926f2ee10654c3bc24cd92af351881`

This section is an append-only evidence record for the current T23 invocation.
The earlier `34fc8efa77cf61d8a9261eaec575bbe111615618` record above remains
historical evidence and is not rewritten. T22's retained `95f7e7a...`
production baseline is also historical input only. Before collecting this
section's evidence, `git fetch origin main` confirmed both `HEAD` and
`origin/main` were exactly `4efb1d346c926f2ee10654c3bc24cd92af351881`.

### Run identity and scope

- Candidate/base: `4efb1d346c926f2ee10654c3bc24cd92af351881`.
- Isolated checkout: `/home/opc/multica_workspaces/me-ee43a71168f9/me-299-159641c76625/workdir/Loom`.
- Branch: `agent/executor/159641c76625`.
- Initial status: `## agent/executor/159641c76625` (clean).
- Final source scope: this file only. No production, Runtime/Storage,
  Validator scenario/test source, schema/migration, CI/workflow, acceptance,
  or other ledger file was changed.
- Evidence-only descendants and generated files do not change the production
  candidate. No PR was created by Executor.
- Race protocol: closed; this record adds no persistence, claim/release,
  retry, checkpoint, marker, or concurrency state.
- Disposition: **current T23 executable/core evidence is passing; final V0
  certification is not claimed.** T22's capability gaps and the CLI external
  endpoint failure remain explicit non-certifying evidence.

### PostgreSQL 18 service and database isolation

The repository procedure `bash tools/postgres-test.sh up` reported healthy
container `loom-postgres-test-1`, image `pgvector/pgvector:0.8.6-pg18`, bound to
`127.0.0.1:15432`. `select version()` reported PostgreSQL `18.6` on
`aarch64-unknown-linux-gnu`.

The T23 databases created for this run were independent databases owned by
`loom` on that service:

- `postgresql://loom:loom@127.0.0.1:15432/loom_t23_certification_4efb1d` —
  fresh database used for the Validator all-target and PG contract runs.
- `postgresql://loom:loom@127.0.0.1:15432/loom_t23_certification_4efb1d_gate2` —
  separate empty database used for the certifying T20 gate report.
- `postgresql://loom:loom@127.0.0.1:15432/loom_t23_certification_4efb1d_gate3` —
  separate empty database used for the workspace aggregate and its T20 run.

The pre-existing `loom_control`, historical `loom_t23_certification`, and
`loom_t24_certification` databases were not used for certifying T23 evidence,
reset, or deleted. The first all-target run necessarily populated fixed test
keys in the first fresh database; a subsequent T20-only attempt there returned
the real `IdempotencyConflict` for `t11.cv016.key1` and did not overwrite that
record. That failed attempt is retained in
`target/validator/t23-4efb1d-logs/t20-gate.log` and is not used as a pass.

### Current required-live T20 evidence

Exact command, against `loom_t23_certification_4efb1d_gate2`:

```text
LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_t23_certification_4efb1d_gate2 LOOM_T20_REPORT_PATH=$PWD/target/validator/t23-4efb1d-pg18-live-gate.json CARGO_INCREMENTAL=0 CARGO_BUILD_JOBS=2 bash tools/validator-pg18-gate.sh
```

Named CI job: `PostgreSQL 18 persistence contract / Validator PostgreSQL 18
live capability matrix gate (VALR-T20)`. Local artifact/report:
`target/validator/t23-4efb1d-pg18-live-gate.json`; execution log:
`target/validator/t23-4efb1d-logs/t20-gate-gate2.log`.

Result: **PASS**, exit 0. The report says
`type=loom-validator.pg18-live-gate`, `backend_evidence=postgresql`,
`backend_evidence_trusted=true`, `gate_passes=true`, and exactly `10 total,
10 pass, 0 fail, 0 skipped, 0 unavailable`. The rows actually executed and
passed were CV-014, CV-016, CV-022, CV-023, CV-030, CV-031, CV-032, CV-033,
CV-039, and CV-040. The report includes controlled-boundary-restart evidence
for every restart-sensitive row; CV-016 observed Accepted then Deduplicated,
one committed EventRef/history row, and durable state after restart.

The workspace aggregate repeated the same exact live matrix once against the
separate empty `loom_t23_certification_4efb1d_gate3` database. Its report is
`target/validator/t23-4efb1d-workspace-pg18-live-gate.json` and independently
records `gate_passes=true`, trusted PostgreSQL evidence, and `10 total, 10
pass, 0 fail, 0 skipped, 0 unavailable`.

### AC mapping and Validator/core evidence

- **AC-1 candidate integrity — PASS.** The exact candidate, isolated branch,
  clean pre-evidence checkout, and old-baseline/current-candidate relationship
  are recorded above. All certifying evidence targets `4efb1d…`; any HEAD
  descendant is evidence-only.
- **AC-2 current T22 checklist — PASS for executable/core evidence.** The
  exact focused command was
  `LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_t23_certification_4efb1d CARGO_INCREMENTAL=0 CARGO_BUILD_JOBS=2 bash tools/test.sh -p loom-validator --all-targets -- --test-threads=1`.
  It executed and passed 165 Validator unit tests; action/ingress 11;
  agency 5; authority-gate 7; backend-evidence 1; change-feed 7; lifecycle
  3; T20 live 2; provenance 9; query/catalog 7; replay/fork 4; required-live
  3; restart-evidence 6; runtime-authority 2; scheduler 8; semantic/blob 11;
  world-binding 10; and world-time 10. The direct tests for CV-018/CV-019 and
  CV-034..CV-037 executed, but T22's missing public/controlled capability
  contract status remains a gap and is not relabeled `ready` here. The
  auxiliary `query_catalog_causal_fixture` target ran 0 tests and is not
  evidence.
- **AC-3 PG18 schema/migration and persistence — PASS.** Against the fresh
  T23 endpoint, these exact CI commands all passed with zero failures/skips:

  ```text
  cargo test -p loom-storage --test postgres_schema -- --nocapture (1)
  cargo test -p loom-storage --test postgres_lifecycle -- --nocapture (4)
  cargo test -p loom-storage --test postgres_lifecycle postgres_18_template_birth_is_atomic_and_snapshots_binding -- --nocapture (1; 3 filtered)
  cargo test -p loom-storage --test postgres_vertical -- --nocapture (1)
  cargo test -p loom-storage --test postgres_read -- --nocapture (1)
  cargo test -p loom-storage --test postgres_commit -- --nocapture (9)
  cargo test -p loom-storage --test postgres_work -- --nocapture (12)
  cargo test -p loom-storage --test postgres_work_stale_completion -- --nocapture (1)
  cargo test -p loom-storage --test postgres_restart_resume -- --nocapture (1)
  cargo test -p loom-storage --test postgres_revision -- --nocapture (2)
  cargo test -p loom-validator --test lifecycle -- --nocapture (3)
  cargo test -p loom-validator --test replay_fork -- --nocapture (4)
  ```

  These named CI jobs covered schema/migration, World lifecycle and Template
  birth/binding, public Runtime/API vertical/read parity, commit/CAS, durable
  Work and stale fencing, restart/resume, Runtime Revision, and replay/fork.
- **AC-4 no hidden failures/skips — PASS for the certifying core matrix.**
  `target/validator/t23-4efb1d-pg18-live-gate.json` preserves all ten row
  results and zero non-pass outcomes. The separate initial-database
  `IdempotencyConflict` failure, CLI external-boundary failure, ledger graph
  failure, and T22 capability gaps are retained below as non-certifying facts.
- **AC-5 reviewable ledger — PASS.** This append-only section records exact
  candidate, branch, database endpoint/name, commands, named CI jobs,
  artifacts/reports, row-level outcomes, failure details, and source scope.

Focused Validator commands were also run separately against the first fresh
T23 URL, each with `--test-threads=1`, and each passed with zero failures/skips:

```text
bash tools/test.sh -p loom-validator --test world_binding -- --test-threads=1
bash tools/test.sh -p loom-validator --test runtime_authority -- --test-threads=1
bash tools/test.sh -p loom-validator --test action_ingress -- --test-threads=1
bash tools/test.sh -p loom-validator --test lifecycle -- --test-threads=1
bash tools/test.sh -p loom-validator --test scheduler -- --test-threads=1
bash tools/test.sh -p loom-validator --test world_time -- --test-threads=1
bash tools/test.sh -p loom-validator --test query_catalog -- --test-threads=1
bash tools/test.sh -p loom-validator --test semantic_blob -- --test-threads=1
bash tools/test.sh -p loom-validator --test replay_fork -- --test-threads=1
bash tools/test.sh -p loom-validator --test agency -- --test-threads=1
bash tools/test.sh -p loom-validator --test change_feed -- --test-threads=1
bash tools/test.sh -p loom-validator --test provenance -- --test-threads=1
```

### Static, security, build, client, SSE, CLI and governance evidence

The following exact checks were run on this candidate, with the named CI jobs
where the repository defines them:

| Check / named job | Exact command | Result |
| --- | --- | --- |
| Architecture policy | `python3 tools/check_architecture.py` / `Rust checks / Architecture policy` | PASS: `Loom architecture dependency policy: OK` |
| Storage SQL ownership | `python3 tools/check_storage_sql_ownership.py` | PASS: `storage SQL ownership check passed` |
| Compose contracts | `docker compose -f compose.test-db.yaml config --quiet`; `docker compose -f compose.yaml config --quiet` | PASS |
| Dependency/security policy | `cargo deny check advisories bans licenses sources` / `Rust checks / Dependency and security policy` | PASS: advisories, bans, licenses, sources all ok |
| Format | `cargo fmt --all -- --check` / `Format` | PASS |
| Check | `cargo check --workspace --all-targets --all-features` / `Check` | PASS |
| Strict clippy | `cargo clippy --workspace --all-targets --all-features -- -D warnings` / `Clippy` | PASS |
| Rustdoc | `RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps` / `Rustdoc` | PASS |
| Workspace tests | `LOOM_TEST_POSTGRES_URL=...loom_t23_certification_4efb1d_gate3 LOOM_T20_REPORT_PATH=.../t23-4efb1d-workspace-pg18-live-gate.json CARGO_INCREMENTAL=0 CARGO_BUILD_JOBS=2 bash tools/test.sh --workspace --all-features` / `Rust checks / Test` | PASS; all executed tests had zero failures/skips; T20 report is trusted 10/10 |
| Authority regression | `LOOM_TEST_POSTGRES_URL=...loom_t23_certification_4efb1d_gate2 CARGO_INCREMENTAL=0 CARGO_BUILD_JOBS=2 bash tools/validator-authority-gate.sh` / Stage-1 authority regression | PASS; six classes, focused suites, stage-1 ledger, architecture and format checks |
| READY unit fixtures | `python3 tools/test_validator_ready.py` / `Validator READY fixtures (unit)` | PASS: 3 tests |
| Stage-1 ledger | `python3 tools/validator_ready.py --root docs/tasks/validator-recert/stage-1 --check --format json` | PASS: `valid=true`, 7 records, no violations |
| Recert ledger governance | `python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json` / `Validator real ledger governance (real task records)` | FAIL, exit 1: `valid=false`; T19/T20/T21 and T24 dependency eligibility remains blocked in the current graph, details in `target/validator/t23-4efb1d-logs/validator_ready_recert.json` |
| CLI required-live boundary | `LOOM_TEST_POSTGRES_URL=...loom_t23_certification_4efb1d_gate2 cargo run -q -p loom-validator -- --all --strict --required-live --json target/validator/t23-4efb1d-validator-all-required-live.json` | FAIL, exit 1: external default endpoint `http://127.0.0.1:8080/`; 32 total, 0 pass, 2 fail (CV-023/CV-024 reconnect-only), 17 skipped, 13 unavailable; report preserves all details |

The CLI/client/SSE unit and integration evidence was included in the passing
workspace and Validator runs: `loom-client` 4 unit tests plus boundary
compatibility, `loom-api` 7 unit tests, `loom-boundary` 10 unit tests, CLI 4
unit tests plus 5 integration tests, and composition public workflows. The
CLI required-live result above is deliberately not upgraded by the ambient PG
URL: the endpoint remained external and did not provide a controlled server
restart.

### Final handoff facts

- Final source diff after evidence collection: only
  `docs/tasks/validator-recert/stage-3/t23-core-integrated-gate.md`.
- Generated reports/logs under `target/validator/` are ignored and are not
  source diff. The current candidate remained unchanged while evidence was
  collected; final `git fetch origin main` and SHA checks reconfirmed
  `HEAD == origin/main == 4efb1d346c926f2ee10654c3bc24cd92af351881` before
  ledger editing.
- The current T22 capability gaps remain explicit: CV-017..CV-019,
  CV-028..CV-029, and CV-034..CV-037 are not converted from unavailable,
  placeholder, or historical evidence into certification Pass. The current
  executable tests for some of these IDs are recorded only as the actual
  focused-test result; they do not provide the missing public/controlled
  Validator contract described by T22.
- Final V0 certification remains unclaimed. Independent Reviewer, CI/merge
  and FINAL_MERGE_GATE actions are outside Executor scope.

## Current-main rerun on production candidate `103a75e96cd9f7b9e495a39bb6608316c47b76e6`

This is an append-only rerun record. All earlier candidate sections, failures,
skips, unavailable results, and historical evidence remain unchanged. The
refreshed T22 manifest was read from evidence-only manifest merge
`322a9268648d243abd6196f508f5c88681c0c6a1`; `git merge-base --is-ancestor`
confirmed that merge is a descendant of the production candidate. The manifest
merge is not used as a production candidate and no production behavior is
changed by this record.

### Run identity, candidate, and scope

- Run date: 2026-08-30 (Asia/Shanghai).
- Isolated checkout:
  `/home/opc/multica_workspaces/me-ee43a71168f9/me-299-9b527e0cda75/workdir/Loom`.
- Branch: `agent/executor/9b527e0cda75`.
- Production candidate/base fixed before evidence collection:
  `103a75e96cd9f7b9e495a39bb6608316c47b76e6`.
- Evidence manifest reference:
  `322a9268648d243abd6196f508f5c88681c0c6a1` (docs-only descendant).
- Initial status: `## agent/executor/9b527e0cda75` (clean) and initial
  `HEAD == 103a75e96cd9f7b9e495a39bb6608316c47b76e6`.
- Final pre-ledger-evidence HEAD remained the exact production candidate; the
  only source change in this descendant is this ledger append. No production,
  Runtime, Storage, Validator scenario/test source, schema/migration,
  CI/workflow, acceptance, or other ledger file was changed.
- `origin/main` was observed to have advanced independently to
  `f0cf50061b31e9f5e5a595ddaa9c71a4eff554d2` after the fixed candidate was
  selected; it was not used to mix or replace this run's candidate. The
  current-main baseline for every result below is the fixed `103a75e…`
  candidate.
- Race protocol: closed. No persistence, receipt, claim/release, retry,
  checkpoint, marker, or concurrency state was added.

### PostgreSQL 18 service and fresh database isolation

`bash tools/postgres-test.sh up` reported healthy
`loom-postgres-test-1`, image `pgvector/pgvector:0.8.6-pg18`, bound to
`127.0.0.1:15432`. `select version()` reported PostgreSQL `18.6` on
`aarch64-unknown-linux-gnu`.

The run created fresh databases owned by `loom`; each was independent of the
sibling T24 database and of all historical/control databases:

- `loom_t23_103a75e_core`: workspace aggregate.
- `loom_t23_103a75e_runtime`, `_action`, `_lifecycle`, `_scheduler`, `_time`,
  `_query`, `_semantic`, `_replay`, `_agency`, `_feed`, `_provenance`: separate
  Validator focus controls.
- `loom_t23_103a75e_contract`: all CI-listed PostgreSQL contract commands.
- `loom_t23_103a75e_gate`: certifying T20 required-live matrix.
- `loom_t23_103a75e_ws`: created for isolation planning; no certifying result
  was attributed to it.

All explicit test URLs were of the form
`postgresql://loom:loom@127.0.0.1:15432/<database>`. No T24 database was
reset, deleted, or used for T23 evidence. The generated reports and logs under
`target/validator/` are ignored and are not source diff.

### Static, security, build, and repository checks

The following commands were executed against the fixed candidate and passed:

| Exact command | Result |
| --- | --- |
| `python3 tools/check_architecture.py` | PASS: `Loom architecture dependency policy: OK` |
| `python3 tools/check_storage_sql_ownership.py` | PASS: `storage SQL ownership check passed` |
| `docker compose -f compose.test-db.yaml config --quiet` | PASS |
| `docker compose -f compose.yaml config --quiet` | PASS |
| `cargo deny check advisories bans licenses sources` | PASS: advisories, bans, licenses, sources all ok |
| `cargo fmt --all -- --check` | PASS |
| `cargo check --workspace --all-targets --all-features` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps` | PASS |
| `python3 tools/test_validator_ready.py` | PASS: 3 tests |
| `python3 tools/validator_ready.py --check --format json` | PASS: `valid=true`, 10 records, no violations |
| `python3 tools/validator_ready.py --root docs/tasks/validator-recert/stage-1 --check --format json` | PASS: `valid=true`, 7 records, no violations |
| `bash tools/validator-authority-gate.sh` | PASS: authority 7, backend 1, restart 6, required-live 3; stage-1 ledger and architecture checks passed |

### Workspace and Validator focus evidence

Workspace aggregate command:

```text
LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_t23_103a75e_core CARGO_INCREMENTAL=0 CARGO_BUILD_JOBS=2 bash tools/test.sh --workspace --all-features
```

Result: **PASS**, exit 0. The named tests actually executed and passed,
including Validator unit 165; action/ingress 11; agency 5; authority gate 7;
backend evidence 1; change feed 7; lifecycle 3; PostgreSQL live gate 3;
provenance 9; query/catalog 7; replay/fork 4; required-live 3;
restart-evidence 6; runtime authority 2; scheduler 8; semantic/blob 11;
world binding 10; and world time 10. Storage tests executed and passed:
schema 1, lifecycle 4, vertical 1, read 1, commit 9, work 12, stale
completion 1, restart/resume 1, and revision 2. All executed test summaries
reported zero failures and zero ignored tests. The auxiliary
`query_catalog_causal_fixture` target reported 0 tests and is not used as
evidence.

Each focus command was then executed separately with
`CARGO_INCREMENTAL=0 CARGO_BUILD_JOBS=1` and `--test-threads=1`, using the
named fresh database below. Every final run exited 0 with the stated tests
executed and zero failures/ignored tests:

| Exact command suffix | Fresh database | Result |
| --- | --- | --- |
| `bash tools/test.sh -p loom-validator --test runtime_authority -- --test-threads=1` | `loom_t23_103a75e_runtime` | PASS, 2 |
| `bash tools/test.sh -p loom-validator --test action_ingress -- --test-threads=1` | `loom_t23_103a75e_action` | PASS, 11 |
| `bash tools/test.sh -p loom-validator --test lifecycle -- --test-threads=1` | `loom_t23_103a75e_lifecycle` | PASS, 3 |
| `bash tools/test.sh -p loom-validator --test scheduler -- --test-threads=1` | `loom_t23_103a75e_scheduler` | PASS, 8 |
| `bash tools/test.sh -p loom-validator --test world_time -- --test-threads=1` | `loom_t23_103a75e_time` | PASS, 10 |
| `bash tools/test.sh -p loom-validator --test query_catalog -- --test-threads=1` | `loom_t23_103a75e_query` | PASS, 7 |
| `bash tools/test.sh -p loom-validator --test semantic_blob -- --test-threads=1` | `loom_t23_103a75e_semantic` | PASS, 11 |
| `bash tools/test.sh -p loom-validator --test replay_fork -- --test-threads=1` | `loom_t23_103a75e_replay` | PASS, 4 |
| `bash tools/test.sh -p loom-validator --test agency -- --test-threads=1` | `loom_t23_103a75e_agency` | PASS, 5 |
| `bash tools/test.sh -p loom-validator --test change_feed -- --test-threads=1` | `loom_t23_103a75e_feed` | PASS, 7 |
| `bash tools/test.sh -p loom-validator --test provenance -- --test-threads=1` | `loom_t23_103a75e_provenance` | PASS, 9 |

The focus tests for CV-028/CV-029, CV-034..CV-037, and scheduler gap rows
executed their fail-closed/scaffold assertions. Those assertions prove the
documented absence of the required public capability surfaces; they are not
capability passes. CV-028 and CV-029 therefore remain explicit blocking gaps
from the refreshed manifest.

Current CV coverage index is: CV-001..CV-004 lifecycle; CV-005..CV-009
replay/fork; CV-010..CV-011 runtime authority; CV-012..CV-014 world binding
and T20; CV-015..CV-017 action/ingress; CV-018..CV-020 scheduler; CV-021..CV-024
World Time; CV-025..CV-027 query/catalog; CV-028..CV-030 semantic/blob and
pinned reads; CV-031..CV-033 provenance and T20; CV-034..CV-037 Agency; and
CV-038..CV-040 change feed and T20. Every range was exercised by the current
candidate workspace/focus/T20 commands above; gap ranges retain their gap
classification rather than being represented as capability passes.

### PostgreSQL contract evidence

Each command below used
`LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_t23_103a75e_contract`
and `CARGO_INCREMENTAL=0 CARGO_BUILD_JOBS=1`, with the exact CI test command
and `--nocapture`. Every named test executed and passed:

```text
cargo test -p loom-storage --test postgres_schema -- --nocapture                         # PASS, 1
cargo test -p loom-storage --test postgres_lifecycle -- --nocapture                      # PASS, 4
cargo test -p loom-storage --test postgres_lifecycle postgres_18_template_birth_is_atomic_and_snapshots_binding -- --nocapture  # PASS, 1; 3 filtered
cargo test -p loom-storage --test postgres_vertical -- --nocapture                       # PASS, 1
cargo test -p loom-storage --test postgres_read -- --nocapture                           # PASS, 1
cargo test -p loom-storage --test postgres_commit -- --nocapture                         # PASS, 9
cargo test -p loom-storage --test postgres_work -- --nocapture                           # PASS, 12
cargo test -p loom-storage --test postgres_work_stale_completion -- --nocapture           # PASS, 1
cargo test -p loom-storage --test postgres_restart_resume -- --nocapture                  # PASS, 1
cargo test -p loom-storage --test postgres_revision -- --nocapture                       # PASS, 2
cargo test -p loom-validator --test lifecycle -- --nocapture                             # PASS, 3
cargo test -p loom-validator --test replay_fork -- --nocapture                           # PASS, 4
```

These results cover schema/migrations, World and Template birth/binding,
public Runtime/API/read parity, commit/CAS, durable Work and stale fencing,
restart/resume, Runtime Revision, and replay/fork on PostgreSQL 18.

### T20 required-live matrix

The certifying matrix used a separate empty database and the repository gate:

```text
LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_t23_103a75e_gate LOOM_T20_REPORT_PATH=$PWD/target/validator/t23-103a75e-pg18-live-gate.json CARGO_INCREMENTAL=0 CARGO_BUILD_JOBS=1 bash tools/validator-pg18-gate.sh
```

Named CI job: `PostgreSQL 18 persistence contract / Validator PostgreSQL 18
live capability matrix gate (VALR-T20)`. Result: **PASS**, exit 0;
`postgres_live_gate` executed 3 tests, all passed. Report
`target/validator/t23-103a75e-pg18-live-gate.json` records
`backend_evidence=postgresql`, `backend_evidence_trusted=true`,
`gate_passes=true`, and exactly **10 total / 10 pass / 0 fail / 0 skipped /
0 unavailable**. The actual required-live rows were CV-014, CV-016, CV-022,
CV-023, CV-030, CV-031, CV-032, CV-033, CV-039, and CV-040. Restart-sensitive
rows include `controlled-boundary-restart`; CV-016 observed Accepted then
Deduplicated, one committed EventRef/history/facet, and durable state after
restart.

### Non-certifying failures, skips, unavailable results, and historical facts

All such outcomes remain explicit and are not promoted to certification:

- A first focus attempt against this checkout failed at compilation with
  `No space left on device` before the target test body ran (FAIL/NOT_RUN).
  Only this checkout's generated `target/` files were cleaned; the focus was
  rerun on fresh databases and passed. This is an environment observation,
  not a production result.
- A subsequent action-ingress attempt against the reused `_core` database
  hung during `cv016_via_pg_with_restart_if_available` after earlier tests had
  populated fixed keys; it was terminated with exit 130 and is
  FAIL/NOT_RUN, not evidence. The final action-ingress run used the fresh
  `_action` database and passed all 11 tests.
- Exact CLI boundary command:

  ```text
  LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_t23_103a75e_contract CARGO_INCREMENTAL=0 CARGO_BUILD_JOBS=1 cargo run -q -p loom-validator -- --all --strict --required-live --json target/validator/t23-103a75e-validator-all-required-live.json
  ```

  Result: **FAIL**, exit 1. The default external endpoint remained
  `http://127.0.0.1:8080/`; machine report counts were **32 total / 0 pass /
  2 fail / 17 skipped / 13 unavailable**. CV-023 and CV-024 failed as
  reconnect-only, and the PG URL did not upgrade external evidence to trusted
  PostgreSQL or real restart evidence.
- CV-028/CV-029 remain blocking manifest gaps. The semantic/blob focus tests
  only prove fail-closed public truth and non-registering scaffold behavior;
  no missing public SemanticService projection or blob/reference operation was
  relabeled as a capability PASS.
- Inherited historical T23 records retain earlier candidate failures,
  IdempotencyConflict observations, filtered/zero-test observations, CLI
  failures, and all prior gap classifications. No historical candidate or
  report substitutes for this `103a75e…` run.

### AC mapping and final diff

- **AC-1:** PASS evidence for candidate discipline. Every final command and
  report above is tied to `103a75e96cd9f7b9e495a39bb6608316c47b76e6`; the T22
  manifest ref `322a926…` is explicitly evidence-only and is an ancestor
  descendant check, not a production baseline.
- **AC-2:** PASS for executable/core evidence. The refreshed ten-domain T22
  manifest was used as checklist; workspace, all Validator focus suites,
  PostgreSQL contracts, T20 matrix, boundary/client/SSE/CLI and static checks
  are recorded with concrete commands and named outcomes. Gap assertions do
  not erase the CV-028/CV-029 capability gaps.
- **AC-3:** PASS for PostgreSQL truth. The service was repository-controlled
  `pgvector/pgvector:0.8.6-pg18`, PostgreSQL 18.6; contract tests and the
  certifying T20 matrix used fresh independent databases. No skip/unavailable
  or external endpoint result is reported as PG evidence.
- **AC-4:** PASS for evidence integrity. The final certifying T20 report is
  trusted 10/10; the CLI fail/skip/unavailable counts, environment
  FAIL/NOT_RUN attempts, historical failures, and CV-028/CV-029 blocking gaps
  remain explicit.
- **AC-5:** PASS for reviewability. This append-only section records the
  candidate/base/branch, manifest relation, DB isolation, exact commands,
  named tests/jobs, report path, row outcomes, failures/gaps, and source
  scope. Final V0 certification is **NOT CLAIMED**.
- Final source diff after this append is only
  `docs/tasks/validator-recert/stage-3/t23-core-integrated-gate.md`. No PR was
  created or merged by Executor; Reviewer, CI merge/final gate, ownership and
  issue status remain outside this execution.
