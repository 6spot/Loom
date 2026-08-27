---
task: VALR-T24
issue: 329
status: in_progress
depends_on: [327]
created_at: 2026-08-27
started_at: 2026-08-27
completed_at:
completion_pr:
merge_sha:
---

# VALR-T24 — Validator certification/integration gate

This record certifies the Validator as an evidence consumer only after the
gate's real test commands and the T22 manifest have been joined. It does not
change Validator, Runtime, Storage, schema, migration, or scenario semantics.
T25 owns the final current-main certification decision.

## Candidate and evidence contract

- Fixed production candidate: `34fc8efa77cf61d8a9261eaec575bbe111615618`.
- The gate accepts this exact production candidate or an evidence-only
  descendant only when the fixed candidate is an ancestor and the complete
  diff contains only these three authorized T24 files: this ledger and the two
  `tools/validator-certification-gate.*` files. Any unrelated base, non-ancestor
  head, or forbidden production diff fails closed before test execution.
- Reports keep `candidate_sha` and `base_sha` fixed at the production SHA and
  record the actual executed commit separately as `evidence_head`.
- Race protocol: closed. No persistence, claim, retry, checkpoint, marker, or
  concurrency authority is introduced.
- Machine-readable artifact: `target/validator/t24-validator-certification-gate.json`.
- Per-CV rows are sorted by CV ID and include outcome, trusted evidence class,
  restart/PG requirement, prerequisite, exact T22 command, executed command ID,
  and evidence log.

## Gate behavior

`bash tools/validator-certification-gate.sh` runs the existing Validator
integration targets, the negative backend/restart/required-live regressions,
the Validator library registry/report tests, and the controlled PostgreSQL 18
T20 gate. Test summaries must be present, must contain no zero-test result,
and must be all-pass before a ready row can be `Pass`. The script does not
convert a shell success into evidence without an executed test summary.

The T22 manifest is authoritative for the row set. Its 31 ready CVs are
reported from the current test commands; its nine capability gaps remain
`Unavailable` with trusted evidence class `none`, and therefore keep
`gate_passes` false. The report also checks duplicate-free deterministic
coverage of all 40 CV IDs represented by T22.

## AC mapping

- AC-1: the library/runner test target records the existing single-pass and
  call-count regressions; the gate invokes each selected target once.
- AC-2: the required-live and Validator library targets exercise strict,
  skipped, unavailable, fail, unknown, and zero-selection fail-closed paths.
- AC-3: `backend_evidence`, `required_live`, and `restart_evidence` targets
  preserve external and reconnect-only negative classifications.
- AC-4: `validator-pg18-gate.sh` runs the controlled PG18 required-live matrix
  and rejects zero-test/self-skip evidence.
- AC-5: the JSON report validates the completed CV registry, ordering, and
  duplicate-free row coverage.
- AC-6: each T22 CV row carries the fixed candidate, evidence head, current
  command evidence, and truthful manifest status; gaps are not hidden.
- AC-7: results below are recorded only from the fixed candidate or its
  authorized evidence-only descendant's real commands;
  no Reviewer/CI/Task completion is asserted here.

## Verification record

The gate's current result is intentionally not a certification pass while T22
contains capability gaps. The exact command and per-command result are stored
in the generated report and are summarized in the handoff comment for this
issue. A nonzero gate result caused by the manifest gaps is expected fail-closed
behavior, not a green certification.

Latest candidate evidence (2026-08-27, fixed candidate above and its
evidence-only descendant):

- `bash tools/validator-certification-gate.sh` — command exit `1` because the
  T22 manifest contains 9 capability gaps; report generation completed with
  `40` CV rows (`31 Pass`, `9 Unavailable`) and `gate_passes: false`.
- The report's 17 underlying commands each had an executed nonzero test
  summary, `0` failed summaries, and exit `0`. This includes the lifecycle,
  replay/fork, runtime-authority, world-binding, action/ingress, scheduler,
  agency, world-time, query/catalog, semantic/blob, provenance, change-feed,
  backend-evidence, required-live, restart-evidence and Validator library
  targets.
- `bash tools/validator-pg18-gate.sh` — PASS inside the gate against a fresh
  repository-managed PostgreSQL 18 database; the structured T20 matrix had 10
  required rows, all trusted PostgreSQL evidence, and `gate_passes: true`.
- `cargo test -p loom-validator --test required_live --all-features -- --nocapture`
  — 3 passed, including unknown/zero selection exit 2 and generic external
  endpoint negative evidence with an ambient PG URL.
- `cargo test -p loom-validator --test restart_evidence --all-features -- --nocapture`
  — 6 passed, including reconnect-only negative and controlled InMemory/PG
  boundary restart evidence.
- `cargo test -p loom-validator --lib --all-features -- --nocapture` — 165
  passed, including single-pass call-count, strict policy, deterministic
  registry/report and duplicate/selection regressions.
