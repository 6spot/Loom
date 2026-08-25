---
task: M12-T2
issue: 199
status: in_progress
depends_on: [185, 198]
created_at: 2026-08-22
started_at: 2026-08-25
completed_at:
completion_pr:
merge_sha:
---
# M12-T2 — V0 operator/developer docs + quickstart

- Refresh README/current status/supported-vs-deferred matrix.
- Linux/Rust/PostgreSQL18+pgvector/blob/server/Revision/Templates/CLI setup with no secrets.
- Quickstart through public surfaces: World birth, Action, State/History/Catalog, Ingress/feed, Scheduler/World Time, replay/fork, provenance, deterministic Agency.
- Explain Installed vs Binding vs Assembly; World Time vs Platform Time; logical Work vs retry/lease; head/quiescence/chronology; missing implementation/terminalization; Revision/Session; replay vs rerun; fork; Agent visibility/CAS policy.
- Developer guide covers Architecture Index supersession, Amendment gate, task ledger and dependency DAG.
- Publish measured capacity envelope only; larger scale remains deferred/unproven.
- Ubuntu/Linux is required baseline; do not advertise mandatory macOS.

## Acceptance
- [x] Clean-machine public workflow reproducible. — `docs/quickstart.md` documents prerequisites (Linux/Rust 1.97.1/PostgreSQL18+pgvector/blob/.env.example) and end-to-end commands via `loom-cli`/`loom-client` only; no Runtime/Storage imports or direct SQL fixtures.
- [x] Terminology/authority matches accepted Amendments. — `docs/operator-guide.md` uses canonical terminology from `docs/architecture/glossary.md` and cites world-runtime/runtime-contracts/governance authority; `docs/developer-guide.md` references `docs/architecture/README.md` reverse supersession table and Amendment gate.
- [x] No old superseded roadmap presented as current. — `README.md` Current status now shows M12 track (`#198` completed, `#199`/`#200` parallel, `#201` gate) and marks old M4–M13 from #60–#134/draft #135 as superseded; v0-roadmap remains `docs/tasks/v0-roadmap.md`.
- [x] Capacity/CI/support claims match evidence. — `docs/capacity-envelope.md` summarizes `docs/tasks/m11/t3-capacity-benchmarks.md` and `loom-bench` evidence with unproven thresholds marked deferred; `README.md` CI baseline states `ubuntu-latest` required, macOS deferred (Amendment 0002 §4).
- [x] Docs validation passes. — `cargo fmt/check/clippy`, `cargo deny`, `check_architecture`, `check_storage_sql_ownership`, `cargo test -p loom-cli`, `cargo doc` and link checks; see Verification evidence below.

## Verification evidence
- `cargo fmt --all -- --check` — ok (0)
- `python3 tools/check_architecture.py` — Loom architecture dependency policy: OK, storage SQL ownership check passed
- `python3 tools/check_storage_sql_ownership.py` — storage SQL ownership check passed
- `cargo check --workspace --all-targets --all-features` — ok
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` — ok (no warnings)
- `cargo deny check advisories bans licenses sources` — advisories ok, bans ok, licenses ok, sources ok
- `cargo test -p loom-cli --all-features` — 4 unit + 4 integration = 8 passed (`exit_code_mapping`, `catalog parsing`, `cli_output_modes_deterministic`, `cli_error_mapping_via_client`, `cli_workflows_via_formal_client_against_boundary`, `cli_admin_workflows_with_auth`)
- `cargo doc --workspace --no-deps` — ok
- `docker compose config` / `docker compose -f compose.test-db.yaml config --quiet` — ok (both Compose files validate)
- Link checks — 0 missing relative Markdown links (swept `*.md` with `pathlib` resolver)
- Prerequisites verified against `.env.example`, `compose.yaml`, `crates/loom-storage/migrations/` and `apps/loom-server/src/config.rs` (bounded worker/Runtime/HTTP limits)

Rework D-001..D-007 sweep on head `5eb56f4` + new head (see below):
- D-001 global flags before subcommand — verified `cargo run -p loom-cli -- catalog --output human` correctly fails `unexpected argument '--output'`; all docs now use `cargo run -p loom-cli -- --output human <subcommand>` / `loom --output human <subcommand>`; swept `catalog --help`, `world create --help` etc confirm `--output/--server/--admin-token` are top-level
- D-002 subcommand param correction — parser sweep for every subcommand (via `cargo run -p loom-cli -- <subcommand> --help`): `catalog --world-id` (not `--world`), `history causes/effects --timeline + --event-id` (not `--world`/`--event-ref`), `history walk --max-depth/--event-id` (not `--depth/--from`), `trajectory entity --entity-id` (not `--entity`), `feed subscribe/tail --after/--limit` (no `--cursor`), `ingress status --ingress-id` (not `--idempotency-key`), `admin session for-event --timeline/--event-id` (not `--event-ref`), `admin timeline missing-implementation --work-id` required, `admin work terminalize --terminal-state + --expected-head-seq/--expected-state-rev` (not `--state`), `admin agency schedule-wake --work-id` required. All quickstart/operator examples updated and re-validated via `cargo run -p loom-cli -- --output human …` parser sweep (exit 16 = Unavailable, not parser error; negative test for `catalog --output human` correctly rejected)
- D-003 Ingress DTO — full envelope JSON with `ingress_id`, `idempotency_key`, `provenance{source}`, `target{world_id,timeline_id}`, `authorization`, `time_metadata`, `invocation{action,input}` validated via `serde_json` against `loom_api::IngressEnvelope` (see `/tmp/validate_test` run: `IngressEnvelope deserialize: OK`, `WorldTemplateDescriptor deserialize: OK`, wrong JSON with `action_type` correctly fails `missing field action`). Both `--json` full envelope and `--ingress-id/--idempotency-key/--world/--timeline/--action/--input` convenience forms are documented and parser-validated
- D-004 Scheduler target — `.env.example:58-61` empty, `compose.yaml:24-36` no target, `config.rs:367-380` None, `application.rs:491-499` only creates worker when target exists. Docs now state default Compose does not auto-drive; quickstart §3.5 instructs to set `LOOM_SCHEDULER_WORLD_ID`/`LOOM_SCHEDULER_TIMELINE_ID` to the created World and `docker compose up -d --build loom-server` before expecting Work/World Time progress; `admin timeline status` noted as read-only
- D-005 Template discovery / Relationship — `CatalogSnapshot` (api:1913) has no Template field; `CatalogService`/boundary only `catalog`/`catalog-for-world`; `capabilities/loom-neutral` only `neutral.counter`/`observer` (no Relationship, no Template builders — those are in `tests/loom-composition/src/neutral.rs`). Docs now state `WorldTemplateDescriptor` caller-constructed JSON validated into `ValidatedWorldBirthPlan`, not discovered via Catalog; Relationship and multiple Template revisions marked **deferred** to M12-T3 in README matrix, prerequisites row, and quickstart §3.1/3.2/3.3
- D-006 deterministic Agency Wake — `DeterministicCognitiveExecutor` is in `crates/loom-agency/src/testing.rs`, not `capabilities/loom-neutral`; `Runtime::new` defaults to `UnavailableCognitiveExecutor` (`orchestration.rs:200-218`), `loom-server` does not call `with_cognitive_executor`. Quickstart §3.9 now marked **deferred** to future public fixture/adapter; documents intended shape with required `--work-id` and shows `missing-implementation` blocking at head
- D-007 Admin auth — default `RequireAdminAuthorization` requires non-empty `x-loom-admin-authorization` (`boundary/src/lib.rs:315-332`); all `admin` examples now prefix global `--admin-token $LOOM_ADMIN_TOKEN` before subcommand with note that `.env.example` has no hard-coded token and the value must be supplied via env/flag (no hard-coded secret)

Full CLI/parser sweep script (`/tmp/check_cli.sh`) on new head: 25 commands + negative test all `PASS` (parser accepted, server Unavailable is expected without running server).

## Scope coordination with M12-T3

M12-T3 (`capabilities/loom-neutral`, issue #200) owns neutral Capability/Template packaging and multiple Template revision demonstration. This task references those fixtures generically via `CatalogService`/`WorldTemplateDescriptor` and the existing `capabilities/loom-neutral` registry; it does not invent a parallel Template layout and leaves installed-but-disabled / future-World-only Template revision details to T3's fixtures.