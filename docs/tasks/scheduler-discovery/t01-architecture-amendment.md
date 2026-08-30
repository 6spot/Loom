---
task: SCHD-T01
issue: 403
status: completed
depends_on: []
created_at: 2026-08-30
started_at: 2026-08-30
completed_at: 2026-08-30
completion_pr: 424
merge_sha: 235d6b53f1f64e49837b0039ad785fe0bb0a22d2
---

# SCHD-T01 — Architecture amendment for automatic Timeline discovery

## Scope

Freeze the minimal architecture change needed to replace deployment-configured
Scheduler targets with automatic bounded discovery in the official server
before implementation work begins.

This record covers only:

- Architecture Amendment 0005;
- the accepted-amendment and reverse-supersession updates in
  `docs/architecture/README.md`;
- the explicit architecture/task evidence for the discovery boundary.

Implementation code, schema/SQL, `LISTEN/NOTIFY`, discovery-level reservation,
public API, bootstrap/default World behavior, new configuration variables and
deferred multi-process topology remain out of scope.

## Architecture decision

`docs/architecture/amendments/0005-automatic-bounded-timeline-discovery.md`
defines discovery as operational/platform observation, not World Truth. The
Application may enumerate bounded Scheduler `TimelineTarget` candidates after
startup, including Timelines with future-World-Time or temporarily
unclaimable Pending Work. Discovery cannot choose or skip a logical head,
claim Work, advance World Time or commit semantic state;
`Runtime::drive_timeline(target, ...)` remains the semantic authority boundary.

The amendment also requires bounded scans to make progress so later stable
Timeline targets cannot be permanently starved, while deliberately leaving
SQL/index/cursor and discovery reservation design to a later implementation
task. Duplicate enumeration by multiple server processes remains an efficiency
concern governed by existing lease/fence/CAS rules.

## Acceptance

- [x] Exact frozen Scheduler/application clauses are named in Amendment 0005
      and the Architecture Index reverse-supersession table.
- [x] Discovery vs Runtime semantic authority is unambiguous.
- [x] Bounded non-starvation is explicit without freezing a SQL/index design.
- [x] Future-World-Time Pending Work remains in discovery semantics.
- [x] The Architecture Index accepted-amendment list is updated in the same
      change.
- [x] Documentation, architecture, compose, format, compile, lint, full
      workspace test and Rustdoc checks pass locally on the candidate.
- [x] Delivery PR #424 merged and completion metadata is reconciled.

## Progress Log

- 2026-08-30 — Started SCHD-T01 from GitHub issue #403. Reviewed the current
  Scheduler/Runtime authority contracts, application composition clauses and
  task-ledger metadata rules.
- 2026-08-30 — Added Amendment 0005 and the Architecture Index mappings. No
  Rust, schema, SQL, configuration, public API or multi-process topology files
  were changed.
- 2026-08-30 — Local architecture, storage-SQL ownership, validator-ledger,
  compose, format, compile, clippy, full workspace test, dependency-policy and
  Rustdoc checks passed; the clean PostgreSQL test volume was used for the
  required live gate.
- 2026-08-30 — Reconciled completion from merged delivery PR #424 at
  `235d6b53f1f64e49837b0039ad785fe0bb0a22d2`.

## Verification Evidence

Verification completed on 2026-08-30:

- `git diff --check` — passed.
- `python3 tools/check_storage_sql_ownership.py` — passed.
- `python3 tools/check_architecture.py` — passed.
- `python3 tools/test_validator_ready.py` — passed.
- `python3 tools/validator_ready.py --check` — passed (existing validator
  leaves reported by the repository ledger are unchanged).
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert
  --check --format json` — valid.
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert/stage-1
  --check --format json` — valid.
- `docker compose -f compose.test-db.yaml config --quiet` and
  `docker compose -f compose.yaml config --quiet` — passed.
- `cargo fmt --all -- --check` — passed.
- `cargo check --workspace --all-targets --all-features` — passed.
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` —
  passed.
- `bash tools/test.sh --workspace --all-features` — passed from a clean
  repository-managed PostgreSQL test volume.
- `cargo deny check advisories bans licenses sources` — passed with
  cargo-deny 0.18.9.
- `RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps` — passed.

Delivery PR #424 merged successfully; the canonical task record now carries its
actual merge evidence.
