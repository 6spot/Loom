---
task: VALR-T05
issue: 310
status: completed
depends_on: [307]
created_at: 2026-08-26
started_at: 2026-08-26
completed_at: 2026-08-26
completion_pr: 334
merge_sha: bcde587c53c04629f805ef5bdf79c9595604dd20
---
# VALR-T05 — Distinguish reconnect from real boundary restart

## Acceptance

- [x] reconnect and restart are separate capability/evidence classes;
- [x] CV-003/CV-004 cannot fake-pass real restart on generic CLI context;
- [x] existing genuine restart integration harness remains live;
- [x] focused tests and repository checks pass.

## Scope

- Validator `backend/context` explicit restart capability model independent of `BackendEvidence`.
- Lifecycle `CV-003/CV-004` guard on true boundary restart before network/scenario side effects.
- InMemory and PostgreSQL test harnesses explicitly declare `controlled-boundary-restart` while preserving the real rebuild of `Runtime` + HTTP boundary on preserved storage.
- Focused regression coverage for restart vs reconnect boundaries.
- No process-control of arbitrary external services and no storage/runtime introspection from production scenario code.

## AC Mapping

- AC-1: `RestartCapability::{ReconnectOnly, ControlledBoundaryRestart}` in `apps/loom-validator/src/backend.rs` (`backend.rs:22`) is a standalone enum with `as_str`/`is_controlled` and `Display`, independent from `BackendEvidence`. `BackendContext::new` and `for_test_api` default to `ReconnectOnly`; controlled interest requires explicit `with_restart_capability`/`with_controlled_boundary_restart`. Debug and scope helpers expose capability without coupling to `BackendEvidence`.
- AC-2: `apps/loom-validator/src/lifecycle.rs` (`lifecycle.rs:473`, `lifecycle.rs:648`) checks `ctx.can_perform_boundary_restart()` before any world/mutation network call. Missing capability returns `ScenarioResult::unavailable` via `reconnect_only_result` with `validator:restart:reconnect-only`, `restart_capability:reconnect-only` and `reconnect-only: endpoint … does not provide controlled application-boundary restart` in `actual`, `reason` and `evidence`. Success paths only execute when capability is `ControlledBoundaryRestart` and themselves emit `validator:restart:controlled-boundary-restart` evidence and `controlled` wording; generic CLI therefore cannot produce a restart-sensitive `pass`.
- AC-3: `apps/loom-validator/tests/lifecycle.rs` (`lifecycle.rs:36`) and `apps/loom-validator/tests/replay_fork.rs` (`replay_fork.rs:105`) explicitly construct `BackendContext` with `with_restart_strategy` + `with_controlled_boundary_restart` wrapping `InMemoryServer::restart` / `PgServer::restart` (`tests/common/mod.rs:171`, `tests/common/mod.rs:359`). Those harnesses still terminate and rebuild the composed service on the preserved `InMemoryStore` / `PgStorage` with a new `TcpListener`/`router_with_admin` boundary; result `actual`/`evidence` strings now state `controlled application-boundary restart via BackendContext::restart`.
- AC-4: `apps/loom-validator/tests/restart_evidence.rs` (`restart_evidence.rs:1`) covers generic external cannot pass, reconnect after stays `ReconnectOnly`, controlled InMemory/PG evidence available, and no overclaim. Repository checks `cargo fmt`, `cargo check`, `cargo clippy -D warnings`, `bash tools/test.sh -p loom-validator --all-features`, `check_storage_sql_ownership.py` and `check_architecture.py` all pass.

## Progress Log

- 2026-08-26 — Introduced independent `RestartCapability` model, made generic `BackendContext` reconnect-only by default, gated `CV-003/CV-004` on real restart capability with explicit `reconnect-only` finding/evidence, and preserved genuine `InMemory`/`PostgreSQL` boundary-rebuild harnesses.
- 2026-08-26 — Added `with_controlled_boundary_restart` to `InMemoryServer`/`PgServer` consumers in `lifecycle` and `replay_fork` integration tests; kept existing replay/fork real restart seam unchanged.
- 2026-08-26 — Added focused regression `tests/restart_evidence.rs` (6 cases) plus CLI subprocess check for `CV-003` on generic `http://127.0.0.1:8080` with `LOOM_TEST_POSTGRES_URL` present, asserting no `pass` and `reconnect-only` in JSON report.
- 2026-08-26 07:22 — Pre-merge candidate verification (rebase to 0719d50, head 620d8eddb3ea9bccd39e5fd1bc96ff839a6e8cea): `cargo fmt --check`, `cargo check --workspace`, `cargo clippy -D warnings`, `bash tools/test.sh -p loom-validator --all-features` (108 unit + restart evidence + all harnesses), `check_storage_sql_ownership`, `check_architecture`, `validator_ready` valid; Leader handoff 01a03cf3-95ff-7adc-8006-3075c073e4d5 at 07:23:11Z recorded as handoff (not approval).
- 2026-08-26 07:34 — Reviewer approval 01a03cfd-cf73-7484-81f3-386b9eeedb5d at 07:34:21Z for PR #334 (head 620d8ed / base 0719d50).
- 2026-08-26 07:35 — PR #334 merged at 07:35:13Z (merge commit bcde587c53c04629f805ef5bdf79c9595604dd20); required CI `Rust checks` + `PostgreSQL 18 persistence contract` SUCCESS.
- 2026-08-26 — Post-merge ledger audit (PR #337 docs-only, base 3445018): `git diff --check` PASS, `validator_ready` valid=true, ready=[], violations=[], ledger status completed; no full Rust re-run post-merge.

## Verification Evidence

- Pre-merge candidate verification (head 620d8ed / base 0719d50, 07:22): `cargo fmt --all` → passed; `cargo fmt --all -- --check` → passed; `cargo check -p loom-validator --all-targets --all-features` → passed; `cargo check --workspace --all-targets --all-features` → passed; `cargo clippy -p loom-validator --all-targets --all-features -- -D warnings` → passed; `cargo clippy --workspace --all-targets --all-features -- -D warnings` → passed; `cargo test -p loom-validator --test backend_evidence --all-features` → passed (1 test); `cargo test -p loom-validator --test restart_evidence --all-features` → passed (6 tests); `bash tools/test.sh -p loom-validator --all-features` → passed (108 unit + all harnesses); `python3 tools/check_storage_sql_ownership.py` → passed; `python3 tools/check_architecture.py` → passed; `python3 tools/validator_ready.py --check --format json` → valid (pre-merge, 07:22).
- Post-merge ledger audit (PR #337 docs-only, base 3445018): `git diff --check` → passed; `python3 tools/validator_ready.py --check --format json` → valid (valid=true, ready=[], violations=[]); GitHub PR #337 net diff vs base 1 file, 17 additions / 22 deletions (docs-only); no full Rust re-run post-merge.
- Reviewer 01a03cfd-cf73-7484-81f3-386b9eeedb5d at 07:34:21Z approved PR #334 (head 620d8ed / base 0719d50); Leader handoff 01a03cf3-95ff at 07:23:11Z was handoff, not approval; merge commit bcde587 at 07:35:13Z; required CI 2/2 SUCCESS.

Acceptance complete: Reviewer approved PR #334, both required CI checks passed, and the merged delivery is recorded above.
