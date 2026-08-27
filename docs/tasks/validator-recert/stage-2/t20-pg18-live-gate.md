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
evidence references, and the exact gate command.

## Verification

Command:

```text
bash tools/validator-pg18-gate.sh
```

With no override, the script starts/reuses the repository-managed local
`pgvector/pgvector:0.8.6-pg18` service. CI supplies its explicit ephemeral
`LOOM_TEST_POSTGRES_URL` and therefore owns that service lifecycle.

Completion evidence is added here after the candidate PR and merge SHA are
known. The CI job uses the repository's pinned `pgvector/pgvector:0.8.6-pg18`
service and archives the deterministic matrix artifact.

## Candidate verification evidence

- `bash tools/validator-pg18-gate.sh` — PASS on the repository-managed
  `pgvector/pgvector:0.8.6-pg18` service; all 10 PG-required rows executed in
  deterministic order and returned `pass`.
- `target/validator/t20-pg18-live-gate.json` — generated with
  `gate_passes: true`, trusted `postgresql` evidence for every row, and
  controlled-boundary-restart evidence for every restart-sensitive row.
- `cargo check -p loom-validator --all-targets --all-features` — PASS.
- `cargo clippy -p loom-validator --all-targets --all-features -- -D warnings`
  — PASS.
- `cargo fmt --all -- --check`, `python3 tools/check_architecture.py`,
  `python3 tools/check_storage_sql_ownership.py`, `cargo deny check
  advisories bans licenses sources`, Compose config checks, and shell syntax
  validation — PASS.

## Acceptance

- [ ] Every PG-required selected scenario has trusted controlled PostgreSQL evidence.
- [ ] No skipped/unavailable row is counted as live-pass.
- [ ] Fake/ambient PG evidence regression remains closed.
- [ ] Machine-readable matrix is deterministic and archived/recorded as completion evidence.
- [ ] CI job completes successfully; review complete.
- [ ] Completion evidence includes PR, merge SHA and exact live-gate result.
