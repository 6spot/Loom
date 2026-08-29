---
task: VALR-T20
issue: 325
status: in_progress
depends_on: [324]
created_at: 2026-08-27
started_at: 2026-08-27
completed_at:
completion_pr:
merge_sha:
---

# VALR-T20 — Stage-2 PostgreSQL 18 live capability matrix gate

This gate certifies only the rows marked PostgreSQL-live-mandatory in the
frozen T08 matrix. It composes the existing T10–T18 executors through the
controlled PostgreSQL test harness and does not change suite behavior, Runtime
semantics, Storage semantics, or the central scenario registry.

## PG-required rows

The gate runs these ten rows in deterministic `CV-` order:

`CV-014`, `CV-016`, `CV-022`, `CV-023`, `CV-030`, `CV-031`, `CV-032`,
`CV-033`, `CV-039`, `CV-040`.

Every row must return `pass` with trusted `postgresql` evidence. Restart-
sensitive rows must expose controlled boundary-restart evidence. Skipped,
unavailable, failed, external, or ambient-only PostgreSQL evidence is a gate
failure and cannot satisfy this record.

## Machine-readable evidence

The gate writes `target/validator/t20-pg18-live-gate.json` (or the path in
`LOOM_T20_REPORT_PATH`). Each row records its outcome, trusted backend evidence
class, restart capability/evidence, prerequisite status, live-PG requirement,
evidence references, and the exact gate command. The rows and report are
serialized from the production executors' structured `ScenarioResult` and
`Finding` values under `ValidationPolicy::required_live()`; the shell wrapper
does not manufacture outcomes from Cargo exit codes. CV-039 and CV-040 run in
separate contexts and retain separate Finding locators.

## Verification

Command:

```text
bash tools/validator-pg18-gate.sh
```

With no override, the script starts/reuses the repository-managed local
`pgvector/pgvector:0.8.6-pg18` service. CI supplies its explicit ephemeral
`LOOM_TEST_POSTGRES_URL` and therefore owns that service lifecycle.

The CI job uses the repository's pinned `pgvector/pgvector:0.8.6-pg18` service
and archives the deterministic matrix artifact at the same root-relative path.

## Candidate verification evidence

- `bash tools/validator-pg18-gate.sh` — PASS on the repository-managed
  `pgvector/pgvector:0.8.6-pg18` service; all 10 PG-required rows executed in
  deterministic order and returned `pass` through the required-live Validator
  path.
- `target/validator/t20-pg18-live-gate.json` — generated with
  `gate_passes: true`, 10 unique per-row evidence references, trusted
  `postgresql` evidence, and controlled-boundary-restart evidence for every
  row.
- `cargo test -p loom-validator --test postgres_live_gate
  t20_required_live_policy_is_fail_closed_for_zero_nonpass_and_ambient_evidence
  -- --nocapture` — PASS for zero-row, `Skipped`, `Unavailable`, `Fail`, and
  external/ambient-only pass paths.
- `cargo fmt --all -- --check`, targeted `cargo test --no-run`, targeted
  `cargo clippy -- -D warnings`, `bash -n tools/validator-pg18-gate.sh`, and
  JSON/schema assertions — PASS.

## Acceptance

- [ ] Every PG-required selected scenario has trusted controlled PostgreSQL evidence.
- [ ] No skipped/unavailable row is counted as live-pass.
- [ ] Fake/ambient PG evidence regression remains closed.
- [ ] Machine-readable matrix is deterministic and archived/recorded as completion evidence.
- [ ] CI job completes successfully; review complete.
- [ ] Completion evidence includes PR, merge SHA and exact live-gate result.

## Current-main required-live rerun after T19 (2026-08-29)

The earlier PR #359 result is historical evidence only. This rerun started from
the post-T19 `origin/main` candidate `7e92033c5b3a14ea30ad8b18bbc68f73145866bb`
(T19 merge `4efb1d346c926f2ee10654c3bc24cd92af351881` is an ancestor). The
working tree was clean before this ledger-only evidence append; no T10–T18
suite, Runtime, Storage, registry, or scenario semantics changed.

The controlled clean PostgreSQL 18 command sequence was:

```text
docker compose --project-name loom -f compose.test-db.yaml down -v
bash tools/postgres-test.sh up
docker compose --project-name loom -f compose.test-db.yaml exec -T postgres-test psql -U loom -d loom_control -Atqc 'SHOW server_version_num;'
LOOM_T20_REPORT_PATH="$PWD/target/validator/t20-current-main-pg18-live-gate.json" CARGO_INCREMENTAL=0 CARGO_BUILD_JOBS=2 bash tools/validator-pg18-gate.sh
```

The first command removed only the repository test container, network, and test
volume. `tools/postgres-test.sh up` recreated the pinned
`pgvector/pgvector:0.8.6-pg18` service and reported `healthy`; PostgreSQL
reported `server_version_num=180006` (`18.6`). The required-live invocation
ran the actual `postgres_live_gate` target: `running 2 tests`, `2 passed; 0
failed`, with no ignored tests. Its report recorded `gate_passes=true`, strict
`required_live=true`, and `10 total, 10 pass, 0 fail, 0 skipped, 0 unavailable`.

The generated artifact was
`target/validator/t20-current-main-pg18-live-gate.json` (SHA-256
`8845971c6ef2f33b43c8324926ed1e44b67fc8e15450387d6c8264fe4a35e142`). Its
deterministic row order and independent evidence locators were:

| CV | outcome | trusted evidence | restart evidence | evidence reference |
| --- | --- | --- | --- | --- |
| CV-014 | pass | postgresql | controlled-boundary-restart | `validator:world_binding:CV-014` |
| CV-016 | pass | postgresql | controlled-boundary-restart | `validator:scenario:CV-016` |
| CV-022 | pass | postgresql | controlled-boundary-restart | `validator:world_time:CV-022` |
| CV-023 | pass | postgresql | controlled-boundary-restart | `validator:world_time:CV-023` |
| CV-030 | pass | postgresql | controlled-boundary-restart | `validator:scenario:CV-030#pinned-stability` |
| CV-031 | pass | postgresql | controlled-boundary-restart | `validator:provenance:CV-031` |
| CV-032 | pass | postgresql | controlled-boundary-restart | `validator:provenance:CV-032` |
| CV-033 | pass | postgresql | controlled-boundary-restart | `validator:provenance:CV-033` |
| CV-039 | pass | postgresql | controlled-boundary-restart | `validator:CV-039:postgresql` |
| CV-040 | pass | postgresql | controlled-boundary-restart | `validator:CV-040:postgresql` |

Artifact assertions passed for exact T08 membership/order, ten unique evidence
references, trusted PostgreSQL evidence on every row, non-empty controlled
restart evidence, and required-live strict policy. The independent negative
test
`cargo test -p loom-validator --test postgres_live_gate
t20_required_live_policy_is_fail_closed_for_zero_nonpass_and_ambient_evidence
-- --nocapture` passed 1 test covering zero rows, `Skipped`, `Unavailable`,
`Fail`, and external/ambient-only pass paths. The required-live runner
regressions passed 3 tests covering unknown selection and external endpoint
fail-closed behavior. T19 registry regressions passed 2 exact Stage-2 tests and
1 `--all` registered-executor test.

Finally, `bash tools/postgres-test.sh down` followed by `bash
tools/postgres-test.sh up` returned the repository service to `healthy`, and
`pg_isready -U loom -d loom_control` returned `accepting connections`. The
current branch candidate is a ledger-only refresh of the post-T19 mainline;
PR/CI status and the eventual merge SHA remain to be supplied by the Leader.
