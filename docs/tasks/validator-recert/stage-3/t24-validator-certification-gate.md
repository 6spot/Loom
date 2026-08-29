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

- Fixed production candidate: `103a75e96cd9f7b9e495a39bb6608316c47b76e6`.
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

The T22 manifest is authoritative for the row set. The refreshed manifest is
read from the pinned `origin/main` ref and records its commit in the report;
it has 38 ready CVs and two capability gaps (CV-028 and CV-029). The two gaps
remain `Unavailable` with trusted evidence class `none`, and therefore keep
`gate_passes` false. The report checks duplicate-free deterministic coverage
of all 40 CV IDs represented by T22.

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

The gate's result is intentionally not a certification pass while T22 retains
CV-028/CV-029 capability gaps. A nonzero gate result caused by those manifest
gaps is expected fail-closed behavior, not a green certification.

### Current-main evidence run

- Candidate/base: `4efb1d346c926f2ee10654c3bc24cd92af351881`.
- T22 input: `origin/main` at `856814dfef5ca800e7c94cdabffd926846663110`,
  `docs/tasks/validator-recert/stage-3/t22-certification-manifest.md`.
- Race protocol: closed; no persistence, claim, retry, checkpoint, marker, or
  concurrency authority was added.
- `bash tools/validator-certification-gate.sh` — exit `1` because the
  refreshed T22 manifest contains the two real gaps CV-028/CV-029. The report
  contains 40 sorted, duplicate-free CV rows: 38 `Pass`, 2 `Unavailable`, and
  `gate_passes: false`.
- All 17 underlying commands executed real tests with zero failed summaries:
  lifecycle (3), replay/fork (4), runtime-authority (2), world-binding (10),
  action/ingress (11), scheduler (8), agency (5), world-time (10),
  query/catalog (7), semantic/blob (11), provenance (9), change-feed (7),
  backend-evidence (1), required-live (3), restart-evidence (6), Validator
  library (165), and the PG18 gate (2 aggregate tests). No required command
  was skipped, ignored, filtered to zero tests, or treated as a pass from an
  unavailable result.
- `bash tools/validator-pg18-gate.sh` — exit `0`; repository-managed
  PostgreSQL 18.6 required-live matrix executed 10/10 rows with trusted
  PostgreSQL evidence, controlled boundary restart evidence, and
  `gate_passes: true` (CV-014, CV-016, CV-022, CV-023, CV-030..CV-033,
  CV-039, CV-040).
- `python3 tools/validator-certification-gate.py --regression-check` — exit
  `0`; boundary termination/rebuild and PG18 preparation failures remain
  fail-closed.

The two non-pass rows are intentionally preserved from the refreshed T22
input: CV-028 lacks the formal semantic-projection observable required by
T08, and CV-029 lacks the formal blob/reference fetch observable required by
T08. T24 does not add a public seam or reinterpret internal controlled-driver
evidence. No PR was created or merged by Executor; final certification remains
owned by T25.

### Current-main rerun on `103a75e96cd9f7b9e495a39bb6608316c47b76e6`

This append-only record supersedes the prior `4efb1d…` run for current-main
evidence. The prior candidate and report remain historical only.

- Candidate/base: `103a75e96cd9f7b9e495a39bb6608316c47b76e6`.
- Evidence HEAD: recorded after the T24-only tooling/ledger update below;
  the production candidate remains unchanged.
- T22 manifest input: merge `322a9268648d243abd6196f508f5c88681c0c6a1`
  (PR #386), read by the gate at the exact manifest ref.
- T19 latest ledger input remains merge
  `6da9989eb9298aa9739a6aa681fbdb8cd9dcde4d`; T23 core evidence input remains
  merge `657e571ced6e06219e9d1a065775d762e4a83279`.
- Race protocol: closed; no persistence, claim, retry, checkpoint, marker, or
  concurrency authority was added.
- The complete 40-row report, command summaries, PG18 report, artifact hashes,
  and exact non-pass reasons are recorded in the handoff comment for this run.
- CV-028 and CV-029 remain truthful `Unavailable` rows because the refreshed
  manifest still lacks the required formal semantic-projection and
  blob/reference-fetch observables. No descriptor, registry entry, or Pass was
  fabricated; final certification remains unclaimed.
