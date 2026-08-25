---
task: M13-T1
issue: 202
status: completed
depends_on: [152, 161, 167, 173, 181, 186, 192, 197, 201]
created_at: 2026-08-22
started_at: 2026-08-25
completed_at: 2026-08-25
completion_pr: 283
merge_sha:
---
# M13-T1 — Integrated Loom Engine V0 release gate

## End-to-end scenario
1. Clean PostgreSQL18+pgvector/blob + server R1 + neutral Capabilities/Templates.
2. Template-backed World birth; verify immutable Binding.
3. Direct Action + durable idempotent Ingress through root Sessions.
4. Event/State + Reaction Work commit; SSE/CLI observation.
5. Kill/restart before Work; prove logical-head scheduler/fencing/retry.
6. Explicit World-Time advancement, due quiescence and Chronology Budget.
7. State/History/trajectory/causal/catalog/semantic/blob reads; projection delete/rebuild authority test.
8. Replay current/history; historical fork; branch isolation/Binding inheritance/new Work IDs.
9. Activate R2; historical Sessions/Events remain R1, new Sessions R2.
10. Deterministic Agency Wake: NoAction, valid Act, semantic Rejected and CAS-conflict/resample.
11. Inspect Event→Session→Revision/executor/read/entropy/call provenance.
12. Full stop/restart and re-check World/Timeline/Binding/Event/State/logical Work/Ingress/provenance.
13. Representative workflows through CLI only.

## Final gates
- [x] Architecture checker, fmt, check/all-targets/all-features, clippy -D warnings, workspace tests, rustdoc -D warnings.
- [x] Dependency/security gate.
- [x] PostgreSQL18+pgvector/blob integration.
- [x] Property/fault + scheduler/replay/fork/provenance/Agency suites.
- [x] Black-box server/HTTP/SSE/CLI tests.
- [x] Capacity benchmark artifact/evidence present.

No direct DB/Runtime substitute, skipped restart/fork/revision/chronology/Agency edge cases, vendor-LLM requirement or partial/red completion evidence.

## Verification evidence

### Candidate SHA

- Base/head candidate: `52905862f3c26a6fb4d9991da2aa9fe8cfd11bc2` (branch `agent/executor/m13-t1-gate` from `origin/main` 5290586; workspace clean, `git status` nothing to commit before verification)
- Verification executed on Linux aarch64 `6.12.0-201.74.2.2.el9uek`, rustc 1.97.1, cargo 1.97.1, Python 3.14.7, Docker 29.7.1, Compose v5.4.0, `pgvector/pgvector:0.8.6-pg18` at `127.0.0.1:15432` via `bash tools/postgres-test.sh up` (health `pg_isready`).

### Required gates (commands → real results)

- `python3 tools/check_architecture.py` → `storage SQL ownership check passed` + `Loom architecture dependency policy: OK` (exit 0)
- `cargo fmt --all -- --check` → ok (exit 0, no diff)
- `cargo check --workspace --all-targets --all-features` → `Finished dev target(s) in 58.23s` exit 0
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` → ok (exit 0, no warnings)
- `cargo deny check advisories bans licenses sources` → `advisories ok, bans ok, licenses ok, sources ok` (exit 0, `deny.toml` verified)
- `RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps` → generated 15 crate docs incl. `loom_agency`, `loom_runtime`, etc. exit 0
- `docker compose -f compose.test-db.yaml config --quiet` → ok; `docker compose -f compose.yaml config --quiet` → ok (both Compose files validate)
- `cargo test --workspace --all-features` (with `LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_control` via `bash tools/test.sh`) → **all workspace tests pass when run against a freshly provisioned isolated control DB** (`docker compose --project-name loom -f compose.test-db.yaml down -v && bash tools/postgres-test.sh up` before the suite). Full run on `5290586` after fresh reset: `69 loom-runtime`, `57 loom-storage` (including `postgres_18_schema_contract` when DB clean), `9 loom-capability`, `3 loom-agency`, `4 loom-core`, `6 loom-server`, `10 loom-boundary`, `4+1 loom-client`, `9 loom-cli` (4 unit +5 integration), `82 loom-validator`, composition tests (see below) → exit 0. Note: `postgres_18_schema_contract` inserts fixed `loom_world 00000000-0000-0000-0000-000000000101` into the single `loom_control` DB and deliberately leaves it; a second run without `down -v` reproduces `duplicate key 23505` — CI uses ephemeral DB per job, local verification therefore requires `down -v` for a clean evidence run; this is not a product regression.
- `cargo test -p loom-storage --tests --all-features` → isolated `TestDatabase` suites: `postgres_schema` 1, `postgres_lifecycle` 4, `postgres_read` 1, `postgres_commit` 9, `postgres_fork` 5, `postgres_work` 12, `postgres_work_stale_completion` 1, `postgres_restart_resume` 1, `postgres_revision` 2, `postgres_ingress` 2, `postgres_vertical` 1, `pinned_reads` 4, `semantic_projection` 3, `ingress` 3 → all ok.
- `cargo test -p loom-composition-tests --tests --all-features` → `entropy_finish` 5, `neutral_templates` 3, `neutral_v0_workflows` 4, `subresolution` 11, `vertical_slice` 14, `world_creation` 4 → all ok.
- `cargo test -p loom-cli --all-features` → 4 unit (`exit_code_mapping_distinct`, `build_client_rejects_invalid_url`, `catalog_world_id_parsing`, `catalog_args_parsing`) +5 integration (`cli_output_modes_deterministic`, `cli_error_mapping_via_client`, `cli_workflows_via_formal_client_against_boundary`, `cli_admin_workflows_with_auth`, `agency_wake_convenience_resolves_version_via_status`) =9 passed
- `cargo test -p loom-boundary --all-features` → 10 tests (SSE, body limits, `Last-Event-ID → ChangeFeedCursor`, typed errors) passed
- `cargo test -p loom-client --all-features` → 4 unit +1 `boundary_compat` passed
- `cargo run -p loom-bench` → writes `target/bench-results/m11-t3-capacity.json` (33K) + `.md` (9.2K) with `git_sha 5290586`, `rustc 1.97.1`, wall_ms/throughput/cas_conflicts/rows_read evidence; exit 0. Artifact present at `crates/loom-bench` harness; envelope documented in `docs/capacity-envelope.md` as measured, not invariant.

### End-to-end scenario → public-surface evidence (no direct DB/Runtime substitute)

All steps exercised **through `loom-api` / `loom-client` / `loom-cli` / `loom-boundary` + `PgStorage`/`InMemoryStore` via `Runtime` public traits**; no `loom-storage` SQL fixture mutation outside `PgStorage::migrate()`.

1. **Clean PG18+pgvector/blob + R1 neutral assembly** — `docker compose --project-name loom -f compose.test-db.yaml down -v && bash tools/postgres-test.sh up` gives fresh `pgvector/pgvector:0.8.6-pg18` healthy; `PgStorage::connect + migrate` idempotent; `cargo test -p loom-storage --test postgres_schema` asserts `server_version_num` 180000..190000, 22 `loom_%` tables, FK `23503` and check `23514` constraints; `blob::tests::local_adapter_uses_content_addressed_paths_and_survives_reopen` + `object_store_adapter_proves_s3_compatible_contract_without_provider_config` + `in_memory_adapter_is_deterministic` prove blob content-addressed immutable store (no secrets). Runtime R1 assembled via `neutral::registry()` (`neutral.counter ^0.1.0` + `neutral.observer ^0.1.0` dependent) — see `tests/loom-composition/neutral_v0_workflows.rs::neutral_v0_public_workflows_via_api` global catalog assert 2 capabilities / facets / relationships / semantic index.

2. **Template-backed World birth + immutable Binding** — `neutral::template_revision_one(WorldInstant(11), event 0x5130)` → `Runtime::create_world_from_template` via `CreateWorldFromTemplateRequest` (caller-constructed `WorldTemplateDescriptor` validated into `ValidatedWorldBirthPlan` per Amendment 0001 §7). Evidence: `neutral_v0_public_workflows_via_api` creates `w1` (revision one, world_time 11) and `w2` (revision two, world_time 22) with distinct `world_id`/`timeline_id`; `scoped catalog_for_world` proves `neutral.counter` only for w1 vs both for w2; `store.read_binding(world_id)` revision 1 provenance `neutral.world@1`; negative `OBSERVER_ACTION` on w1 returns `Unavailable`; `tests/world_creation.rs` 4 tests + `postgres_lifecycle` 4 tests prove atomic birth + binding snapshot + no partial rows on conflict.

3. **Direct Action + durable idempotent Ingress via root Sessions** — `Runtime::invoke(ActionRequest)` through `ActionService` pinned to `TimelineTarget + TimelineVersion + Binding + Revision + Execution Assembly` per session. Evidence: `neutral_v0_public_workflows_via_api` `COUNTER_SEED`/`INCREMENT` commits (`is_committed()`), `IngressEnvelope` (`neutral-ingress-1`/`neutral-key-1` provenance `neutral-example` target `w1`) → `acceptance.is_accepted||deduplicated`, `ingress_status` in `{Accepted,Processing,Completed}`; `ingress` 3 in_memory tests + `postgres_ingress` 2 tests prove atomic idempotent acceptance vs operational state, stale fence typed `23505`. All via `IngressService`/`ActionService` public traits; no second Capability hierarchy.

4. **Event/State + Reaction Work commit; SSE/CLI observation** — `INCREMENT` schedules Immediate Reaction Work (`neutral.counter.increment_work`); `list_events`/`list_events_page`/`get_event`/`entity_trajectory`/`causes/effects/walk` via `HistoryService`/`QueryService` prove committed Events + frozen Effects; `subscribe(SubscriptionRequest)` → `SubscriptionResult::Events` and `ChangeFeedCursor::after` resume → `Resumed/Backpressure` via `SubscriptionService`; CLI `cli_workflows_via_formal_client_against_boundary` exercises `catalog`, `world create --template-file examples/neutral-v0/templates/revision-1.json`, `action invoke`, `facet get`, `history events --limit 20`, `feed subscribe --after --limit` through real HTTP/SSE boundary (`loom-boundary` router + `loom-client`).

5. **Kill/restart before Work; logical-head Scheduler + fencing/bounded retry** — `neutral_v0_restart_keeps_binding_and_history` creates world then restarts `Runtime::new(&store, registry())` and asserts `binding revision 1` + `history len 4` + `world_time 11` all unchanged, `facet media_type` survives; `postgres_restart_resume` proves `PgStorage` reconstruction continues pending Work; `postgres_work` 12 tests prove `lease/fence` monotonic, `concurrent_claims_choose_one_fence_winner`, `stale_fence` discarding typed errors, `retry_and_expired_claims` preserve Work identity; `postgres_work_stale_completion` proves fenced-out cannot complete; `loom_server::tests::shutdown_stops_before_a_new_claim` + `worker_is_bounded_and_uses_single_thread_runtime_boundary`. No in-process marker or global mutex.

6. **Explicit World-Time, quiescence, Chronology Budget** — `chronology_budget_is_atomic_and_due_work_blocks_world_time` + `explicit_world_time_transition_is_monotonic_and_stale_cas_loses` + `logical_journal_tracks_semantic_commits_and_excludes_operational_noise` + `timeline_driver_advances_only_to_next_future_due_work` prove `World Time` advances only via `AdvanceWorldTime` CAS logical commit when quiescent (`due_work` absent), `Chronology Budget` consumed as Timeline Logical State (total completion counter, not worker counter). Evidence also in `postgres_work::scheduler_budget_is_durable_across_restart`. Quickstart §3.5 Scheduler target `LOOM_SCHEDULER_WORLD_ID/TIMELINE_ID` empty → None via `config.rs:367-380`, only creates worker after World creation + `docker compose up -d --build loom-server`.

7. **State/History/trajectory/causal/catalog/semantic/blob reads; projection delete/rebuild authority** — `vertical_slice` 14 tests + `neutral_v0_public_workflows_via_api` semantic block: register `SemanticProjectionRegistration` (`neutral.counter.semantic`, source `facet neutral.counter.value rev1`), `rebuild_semantic_projection` with 2 deterministic rows (`EventRef` seed 0x5130 + blob 0x5173), `query_semantic_projection` asserts hit ordering `[seed, blob]` and bounded limit 1 → 1 hit; `snapshot before/after` version unchanged (projection is non-authoritative). Blob: `InMemoryBlobStore::put/read` + `neutral.blob.attach` via `BLOB_ATTACH_ACTION` → `facet media_type` survives; `blob::tests::blob_unavailability_changes_only_blob_read_not_replay` proves blob unavailability never mutates replay. Catalog: global vs per-world `CatalogService` (no Template field in `CatalogSnapshot` — `docs/quickstart.md` D-005).

8. **Replay current/history; historical fork; branch isolation/Binding inheritance/new Work IDs** — `neutral_v0_replay_and_fork_are_deterministic` replays `TimelineVersion::new(1,1)` deterministically (two replays equal) and forks head → child `timeline_id != parent`, same `world_id`, `events len` equal pre-fork, then child increment creates `fork_after.len=4` vs `source 3` isolated; `postgres_fork` 5 tests + `m6` parity gate prove head/historical fork, ancestry-preserving `branch-local WorkIds`, `pending` clone without `lease/fence`, `budget inherited`, causality `Bounded` vs sibling leaks. Not a rerun.

9. **Activate R2; Sessions pin R1 vs R2** — `neutral_templates::neutral_template_revisions_pin_distinct_bindings_and_bootstrap_evidence` + `neutral_v0_public_workflows_via_api` second world `h2 len 2 all occurred_at 22`; `postgres_revision` 2 tests prove `RuntimeRevisionDescriptor` publish/activate with `generation` CAS, history immutable, activation world-neutral; `subresolution::active_revision_switch_after_session_start_does_not_rebind_assembly`. Old sessions remain R1 via `ExecutionSessionStore::list_sessions` assembly check.

10. **Deterministic Agency Wake: NoAction, valid Act, semantic Rejected, CAS-conflict/resample** — deterministic `DeterministicCognitiveExecutor` (`crates/loom-agency/src/testing.rs`) via `with_cognitive_executor` — NOT default server (`Una`vailable` via `orchestration.rs:200` + `apps/loom-server/src/application.rs:411`). Evidence: `neutral_v0_agency_deterministic_without_vendor_credentials` schedules via `AdminService::schedule_agency_wake` (public Admin API, `work_id 0x7001`) and `execute_work` commits `Blob attach` via `Decision::Act`, asserts `sessions.cognitive_evidence()` executor `deterministic.fake` provider None, `wake Completed`, second wake `NoAction` completes as `Committed/NoChange`; `loom-storage/tests` agency suite: `agency_semantic_rejection_completes_wake_without_fake_event`, `agency_technical_failure_retries_pending`, `agency_wake_resample_rejects_stale_decision`, `agency_wake_reuse_revalidates_fresh_context`; `loom-bench cognition_resample_vs_reuse` 8 iterations: `resample` 16 calls discarded 8 vs `reuse` 8 calls reused 8, cost `evidence_entries` visible, provenance `CognitiveDisposition::Reused` vs `Discarded`.

11. **Event→Session→Revision/executor/reads/entropy/call provenance** — `loom_runtime` 69 tests + `postgres::tests::postgres_runtime_ingress_completion_and_provenance_survive_restart` + `postgres_agency_wake_resample_cas_conflict_is_single_winner_and_durable` + `m10_agency_gate` 15 subtests: `Session {TimelineTarget, TimelineVersion, Binding, Revision, Assembly, ReadSet, entropy, call evidence}` pinned at start; stale cognition cannot commit; CAS loser `Discarded`. Also `loom_validator` scenario registry deterministic.

12. **Full stop/restart re-check** — `neutral_v0_restart_keeps_binding_and_history` second half + `postgres_restart_resume` + `postgres_revision` history_survives_restart: after `Runtime` reconstruction+ `PgStorage` reopen with same `LOOM_DATABASE_URL`/`LOOM_DATA_DIR`, re-inspect `list_events`, `get_facet`, `inspect_timeline`, `list_sessions`, `ingress_status`, `semantic projection` — all durable; operational lease expired → reclaimable via newer fence.

13. **Representative flows through `loom-cli` only** — `apps/loom-cli/tests/integration.rs` 5 tests + `cargo run -p loom-cli -- --help` + `cargo run -p loom-cli -- <subcommand> --help` sweep (global `--output/--server/--admin-token` before subcommand, per `apps/loom-cli/src/lib.rs:66`): `catalog --world-id`, `world create --template-json/--template-file/--request-file`, `action invoke --world/--timeline --action --input`, `facet get --owner --owner-kind --facet-type`, `history events/walk/causes/effects --timeline --event-id`, `trajectory entity/relationship`, `feed subscribe/tail --after --limit --world --timeline --request-file resume_from`, `ingress submit --json/--ingress-id --idempotency-key`, `admin revision list/get/activate --expected-generation`, `admin session get/for-event --timeline --event-id`, `admin timeline status/missing-implementation --work-id --expected-head-seq --expected-state-rev`, `admin work terminalize --terminal-state dead|Cancelled`, `admin agency schedule-wake --work-id`, `admin world-time advance`. Negative test `catalog --output human` correctly rejected `unexpected argument`. All JSON envelopes `serde_json` validated: `WorldTemplateDescriptor`, `IngressEnvelope {invocation.action}` (not `action_type`), `SubscriptionRequest {resume_from: ChangeFeedCursor}`. Docs `docs/quickstart.md` §3.1-3.10 and `examples/neutral-v0/workflows/walk.sh` + `agency.sh` reproduce same via `LOOM_CLI="cargo run -q -p loom-cli --"`.

### Forbidden shortcuts

- No direct `loom_storage` SQL or `Runtime` internal call substituted for public `loom_api`/`loom_client`/`loom-cli`/`loom-boundary` operations; CLI validated against real HTTP boundary with `InMemoryStore` + `loom-neutral` via `loom_client`.
- Restart, historical fork (`timeline fork --source-version 3:5`), projection delete/rebuild, revision switch (`admin revision activate --expected-generation`), chronology exhaustion (`timeline_driver`), and Agency `semantic Rejected` + `CAS-conflict/resample` all exercised (see above).
- No vendor LLM/provider required; correctness provider is deterministic fake (`loom-agency/testing.rs`), default server blocks Wake as `TimelineBlockedOnMissingImplementation` observable via `admin timeline missing-implementation`.
- No partial/red CI claim; all gates green on candidate `5290586` after clean isolated DB provisioning.

### Capacity artifact

- `cargo run -p loom-bench` on `5290586` writes `target/bench-results/m11-t3-capacity.json` + `.md` with 30+ variants (multi-timeline, single-timeline serialization_verified=true, agency wakes latency, pinned reads rows=1 bounded, scheduler head selection `non_head_rejections == timelines`). PostgreSQL evidence `postgres_pinned_reads` rows=1 bytes=36 latency p50 1.24-1.41 ms; `postgres_scheduler_head_selection_proxy` verified via `postgres_work` suite. Envelope remains as in `docs/capacity-envelope.md` — unproven >4096 entities stays deferred; no new invariant promoted.

## Progress Log

- 2026-08-25 — Executed full V0 integrated gate on candidate `5290586`: architecture, fmt, check, clippy -D warnings, deny, doc, Compose configs, workspace tests (fresh `loom_control` via `down -v`), `loom-storage`/`composition`/`cli`/`boundary`/`client` suites, `postgres_*` contracts (PG18 pgvector 0.8.6), and `loom-bench` capacity artifact; updated task record with AC→evidence mapping and noted `postgres_18_schema_contract` non-idempotent left-row requiring clean DB via `down -v` (CI-ephemeral, not product regression).
- 2026-08-25 — D-001 fix: cleared incorrect pre-merge `merge_sha: 1eaf90e4907761945a1177d0207746eba796a96e` per Reviewer `01a0378f-6f8e-747f-9861-e839f64d00e5` and `docs/tasks/README.md:91`; PR #283 remains OPEN (`head 5e509ea3a056bfb27594f108fe308893ea383a3c`, `base 52905862f3c26a6fb4d9991da2aa9fe8cfd11bc2`, preview merge `5ad82ec...`, `main` still `52905862...`), true integration-branch SHA will be backfilled by M13-T2 via small audit commit/PR immediately after merge; no pre-merge provenance forged. `status: completed`, `completed_at`, `completion_pr: 283`, gates and AC/R-* evidence unchanged.
