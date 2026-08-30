---
task: SCHD-T21
issue: 423
status: in_progress
depends_on: [418, 419, 420, 421, 422]
created_at: 2026-08-30
started_at: 2026-08-31
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T21 — Run final one-command Compose/PostgreSQL Scheduler discovery gate

## Goal

Certify the completed automatic Scheduler discovery path on one exact
candidate using official Linux Docker Compose and PostgreSQL 18.

## Scope and acceptance

- [x] Record one candidate SHA and use a clean/controlled data root.
- [x] Prove `docker compose up -d` starts PostgreSQL and `loom-server` with no
      target IDs, then execute the T18 new-World, T19 fork and T20 real
      restart/resume scenarios.
- [x] Confirm active docs/config contain no target-ID activation contract and
      run architecture, task-graph, SQL ownership, format/check, strict
      clippy, workspace tests, Rustdoc, dependency and real PostgreSQL 18
      checks on the same candidate.
- [ ] Reconcile T01–T21 records truthfully with PR, merge SHA, CI and live-gate
      evidence. The evidence PR and its eventual merge SHA remain pending
      until the delivery is merged and the canonical default branch is
      re-read.

This gate may adjust orchestration/evidence only. It must reopen the owning
implementation leaf for semantic fixes and may not weaken a live scenario or
add a bus, worker pool, bootstrap or replacement config feature.

## Candidate and live-gate evidence

- Candidate: `6a4279e63273b8a53742af8c118e984ebd93f07b` (`origin/main`, PR
  #457 merge). All live scenarios below ran against this exact candidate.
- Runtime: Linux; official PostgreSQL image
  `pgvector/pgvector:0.8.6-pg18`, server version `18.6`.
- The three fresh controlled roots were `target/t21-compose-gate-6a4279e`,
  `target/t21-t19-compose-6a4279e` and `target/t21-t20-compose-6a4279e`.
  Each official Compose project was isolated and stopped or torn down after its
  run.

### Official Compose deployment and T18

`LOOM_DATA_DIR=target/t21-compose-gate-6a4279e LOOM_PORT=18080 docker compose
--project-name loom-t21-gate-6a4279e -f compose.yaml up -d --build --wait
--wait-timeout 120` started both services healthy. `docker compose ps` reported
healthy `loom-server` and `pgvector/pgvector:0.8.6-pg18`; `/v1/catalog` returned
HTTP 200 after readiness.

The inspected server environment contained normal bind/database/data,
ingress, lease/retry and worker poll/limit settings only. Neither
`LOOM_SCHEDULER_WORLD_ID` nor `LOOM_SCHEDULER_TIMELINE_ID` was present, and no
target-ID variable was rendered by Compose. After readiness, a World and
Timeline were created through `POST /v1/worlds/from-template`; a public
`neutral.counter.increment` Action committed through `POST /v1/actions`.
Formal Admin, Facet and History reads then observed automatic progression (the
observed history reached sequences 1–200 while the bounded chronology drained),
without restart, rebuild, manual drive or direct SQL assertions.

### T19 fork live gate

`LOOM_DATA_DIR=target/t21-t19-compose-6a4279e LOOM_PORT=18081 docker compose
--project-name loom-t21-t19-6a4279e -f compose.yaml up -d --wait
--wait-timeout 120` ran against a fresh root with only existing operational
poll/chronology settings. The source World was created after readiness, then a
child Timeline was forked through the public client and given a child-only
`neutral.counter.increment` Action. Public Admin/Facet/History reads observed
child head sequence 3, one completed/one pending obligation, facet value 5
and history sequences 1–6; the parent remained at head sequence 1, facet value
1 and history count 1. Both services were healthy and the project was brought
down cleanly. No target IDs or manual drive were used.

### T20 restart/resume live gate

`LOOM_DATA_DIR=target/t21-t20-compose-6a4279e LOOM_PORT=18082 docker compose
--project-name loom-t21-t20-6a4279e -f compose.yaml up -d --wait
--wait-timeout 120` ran with `LOOM_WORKER_POLL_MS=120000` and the existing
chronology-completion bound only, leaving one real Pending obligation before
the first server was stopped. The first server PID was `379716`; the second
server PID after starting the same Compose deployment was `380007`. PostgreSQL
and the data root were preserved across that boundary. Public Admin/Facet/
History reads after restart observed version 3, one completed/one pending
obligation, work count 2, facet value 3 and history sequences 1–3. The
inspected environments had no target IDs and no cursor transfer; the project
was then brought down cleanly.

## Static, test and CI evidence

- `python3 tools/check_architecture.py` — PASS.
- `python3 tools/check_storage_sql_ownership.py` — PASS.
- `python3 tools/test_validator_ready.py` — PASS (3 tests).
- `python3 tools/validator_ready.py --root docs/tasks/scheduler-discovery
  --check --format json` — PASS with no violations after T16–T20
  reconciliation.
- `docker compose -f compose.yaml config --quiet` and
  `docker compose -f compose.test-db.yaml config --quiet` — PASS; active
  documentation/config scans found no target-ID activation contract.
- `cargo fmt --all -- --check` — PASS.
- `cargo check --workspace --exclude loom-validator --all-targets
  --all-features` — PASS.
- `cargo clippy --workspace --exclude loom-validator --all-targets
  --all-features -- -D warnings` — PASS.
- `cargo test --workspace --all-features --exclude loom-storage
  --exclude loom-validator` — PASS, including the Scheduler application unit
  and T18/T19/T20 integration coverage.
- `RUSTDOCFLAGS='-D warnings' cargo doc --workspace --exclude loom-validator
  --no-deps` — PASS.
- `cargo deny --version` reported `cargo-deny 0.18.9`; `cargo deny check
  advisories bans licenses sources` — PASS.
- `LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_t21_scheduler_gate_6a4279e
  cargo test -p loom-storage --all-features --lib -- --test-threads=1` — PASS,
  65/65 tests on a fresh PostgreSQL 18 database. Every CI PostgreSQL target
  also passed on that database: `postgres_commit` 9, `postgres_fork` 5,
  `postgres_ingress` 2, `postgres_lifecycle` 4, `postgres_read` 1,
  `postgres_restart_resume` 1, `postgres_revision` 2,
  `postgres_scheduler_discovery` 3, `postgres_schema` 1,
  `postgres_vertical` 1, `postgres_work` 12 and
  `postgres_work_stale_completion` 1 (42/42 integration tests).
- Focused live gates passed: T18 `world_created_after_server_start_is_auto_scheduled_over_public_http`, T19 `t19_fork_auto_schedule`, and T20 `scheduler_restart`; the T20 evidence includes distinct process IDs, lease expiry, fence reclamation, retry attempt 3, `counter=1->2`, `history=2->3`, `cursor_reused=false`, `scheduler_target_configured=false` and stale-fence rejection.
- The candidate's merged PR #457 CI run `33334223399` passed Classify
  changes, Active deployment documentation, Task ledger governance,
  Dependency and security policy, Rust checks, PostgreSQL 18 persistence
  contract and Compose config. The prior delivery PRs are recorded above in
  T16–T20 with their merge SHAs and CI runs.

## Governance reconciliation

T01–T15 were already completed on the canonical ledger. This gate reconciles
T16–T20 to their actual merged delivery PRs and SHAs: #453 /
`37f81a12116b8bcd1b697c39f927bf996a41ff0c`, #457 /
`6a4279e63273b8a53742af8c118e984ebd93f07b`, #456 /
`3b40633b70f232d64927f75ece461dec63b56897`, #454 /
`937de28f56bfb4034eb28e8b91cca74b5d732d85` and #455 /
`c508f6173b0c6a16dadf0af52bd2b50c590f889`. T21 remains `in_progress` until
this evidence-only delivery is merged; its `completion_pr` and `merge_sha`
are intentionally blank rather than claiming an unmerged SHA.
