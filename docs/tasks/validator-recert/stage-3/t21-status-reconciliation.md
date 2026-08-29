---
task: VALR-T21
issue: 326
status: in_progress
depends_on: [325]
created_at: 2026-08-27
started_at: 2026-08-27
completed_at:
completion_pr:
merge_sha:
---

# VALR-T21 — Reconcile V0 roadmap/README/Task-Ledger status without rewriting history

This record reconciles current-status wording and registers the current-main
Validator re-certification graph. It is documentation and ledger/index work
only. It does not certify V0, complete the recertification root, or replace the
historical M13 evidence.

## Current-status inventory

| Source | Status claim after reconciliation |
| --- | --- |
| Root [`README.md`](../../../../README.md) | Actual current `main` and current T20 baseline are `103a75e96cd9f7b9e495a39bb6608316c47b76e6` (PR #384); T22 re-review is pending/in progress, T23/T24/T25 have no current-main evidence, and T25 remains the final gate. |
| [`docs/tasks/README.md`](../../README.md) | M4–M13 and the former PR #381 / `4efb1d…` / `6da9989…` / `ef281f8…` status snapshots remain historical; T20 is current at `103a75e…`, T22 is under parallel re-review, and T23/T24/T25 remain pending. |
| [`docs/tasks/v0-roadmap.md`](../../v0-roadmap.md) | M4–M13 is historical; current main/T20 baseline `103a75e…`, post-rollback lineage, T22 re-review, later pending gates and the T25 boundary are explicit. |
| [`docs/tasks/validator-recert/README.md`](../README.md) | Exact PR/SHA/CI maps current T20 PR #384 evidence, T22 parallel re-review, no current-main T23/T24/T25 evidence, and historical `4efb1d…`/`6da9989…`/`ef281f8…` records. |
| [`stage-3/README.md`](README.md) | T20 is current-main done at PR #384; T22's existing manifest is under parallel re-review; T23/T24/T25 have no `103a75e…` evidence; T21 remains in progress and T25 is final. |
| Historical [`docs/tasks/validator/README.md`](../../validator/README.md) | Existing Validator initiative and VAL-T1..T10 records remain unchanged and are not marked complete by this recertification tree. |

The inventory is deliberately limited to current-status/governance sources; it
does not rewrite unrelated task evidence or architecture history.

## Current main and evidence snapshot

Actual current `main` and the current T20 evidence baseline are exactly
`103a75e96cd9f7b9e495a39bb6608316c47b76e6`, the PR #384 merge. Its
post-rollback lineage is PR #382 merge
`a898e5be6e33f5f448992c7ddb642af7336bc8f8`, PR #383 merge
`7e92033c5b3a14ea30ad8b18bbc68f73145866bb`, then PR #384 head
`d6654ca09d0c9d46701288054090a9bcbddc31af`; PR #384 CI run `33250772703`
passed both required jobs and its T20 ledger records 10/10 trusted PG18 rows.
The former PR #381 reconciliation, candidate
`4efb1d346c926f2ee10654c3bc24cd92af351881`, snapshot/base
`6da9989eb9298aa9739a6aa681fbdb8cd9dcde4d`, prior actual-main
`ef281f886480663a94193f738179d14933040a12` and their T20/T22/T23/T24
results are retained as historical/superseded. T22's existing manifest is
under parallel current-main re-review; T23/T24/T25 have no current-main
evidence on `103a75e…`. None of these records constitutes certification.

| Task | Current issue/PR state | Candidate/snapshot evidence disposition |
| --- | --- | --- |
| T19 / ME-295 | Issue `done`; PR #379 merged (head `f1f36856b6e33d41e59d6cfe81eada39f289b43f`, base `7716c1c33cd08cde57e8226ca063c6c83c650e8e`, merge `6da9989eb9298aa9739a6aa681fbdb8cd9dcde4d`), CI run `33221134508` passed both required jobs | Historical snapshot controlled registry evidence remains the exact 32-ID set; CV-018/019/028/029/034..037 remain unregistered gaps. |
| T20 / ME-296 | Issue `done`; PR #384 merged (head `d6654ca09d0c9d46701288054090a9bcbddc31af`, base `7e92033c5b3a14ea30ad8b18bbc68f73145866bb`, merge `103a75e96cd9f7b9e495a39bb6608316c47b76e6`), CI run `33250772703` passed both required jobs | Current-main T20 evidence: 10/10 trusted PostgreSQL 18 rows on `103a75e…`; the T20 owner ledger is not rewritten here. |
| T22 / ME-298 | Issue `done` for existing manifest; PR #377 merged (head `d3232672c31a133ca6f5f3172e306ea768259c4c`, base `657e571ced6e06219e9d1a065775d762e4a83279`, merge `856814dfef5ca800e7c94cdabffd926846663110`), CI run `33190567067` passed both required jobs | Current-main re-review is in progress in parallel; no new `103a75e…` evidence is recorded by T21. The 38-ready/CV-028/CV-029 result remains historical snapshot evidence. |
| T23 / ME-299 | Issue `backlog`; PR #376 merged (head `92a2a8eb763976b65f84b889b4de95a9124e6fce`, base/candidate `4efb1d346c926f2ee10654c3bc24cd92af351881`, merge `657e571ced6e06219e9d1a065775d762e4a83279`), CI run `33182385085` passed both required jobs | No current-main evidence exists for `103a75e…`; the former passing core result remains historical/superseded. |
| T24 / ME-300 | Issue `backlog`; PR #378 merged (head `5d77ddda808f5594c2efe3b8c169f82814d6898b`, base `856814dfef5ca800e7c94cdabffd926846663110`, merge `7716c1c33cd08cde57e8226ca063c6c83c650e8e`), CI run `33193706827` passed both required jobs | No current-main evidence exists for `103a75e…`; the former snapshot gate remains fail-closed at 38 `Pass`, 2 `Unavailable` (CV-028/CV-029), `gate_passes: false`, and is not certification. |

The superseded 2026-08-28 `95f7e7a...` snapshot is retained as historical
evidence: its
production candidate was `95f7e7a0233cfa917d0c9656b990fd2af4996874` (PR #365
merge, CI run `33150850081`), with integration base
`bed2dac9947d5c5f92e0d530378f5be712e041a6`. Its T20 row recorded the older
PR #359 clean 10/10 result and a pending fresh rerun; T22 recorded PR #366
merge `7cd6844ff3459b5dad200a2807c452ad70195efc`; T23 recorded PR #363 merge
`6c132cd43e5e7f5f0e5649e938f319f3c1e04197`; and T24 recorded PR #362 merge
`6f22531a909d0becd1d7b30836168f76cd3d5d33`. Those pending/current claims are
superseded, but the old candidate, PR/SHA/CI facts and all old
`31 Pass / 9 Unavailable` / `gate_passes: false` and blocked-CV evidence remain
historical/non-current rather than deleted or rewritten.

The old CV-017 fault-injection blocker and old blocked conclusions for CV-018,
CV-019, CV-028, CV-029, and CV-034..CV-037 remain preserved and explicitly
historical/non-current in the owner records. No owner ledger is edited by T21.

## Historical evidence boundary

The following M13 facts remain exact and explicitly historical:

- M13-T1 candidate: `52905862f3c26a6fb4d9991da2aa9fe8cfd11bc2`;
- M13 integration merge: `19c797d3e1e8bd20a21cda419789793623c5ca1f`, via PR #283;
- M13-T2 closure-audit merge: `dca5463a341bcb4cde19a999eba8ef37e0ea60dd`.

The Stage-1 and Stage-2 `validator-recert` ledgers are post-M13
authority-fix/public-surface history. They are not silently converted into
evidence for current-main certification. T20's completed issue baseline is PR
#359 at merge `8761991c36c07b7ee32d2643228bfb458fdeb2d0`; T21 does not rewrite
the T20 ledger.

## Current graph and certification boundary

| Task | Issue | Dependency | Current state | Record |
| --- | ---: | --- | --- | --- |
| VALR-T21 | [#326](https://github.com/6spot/Loom/issues/326) | #325 / T20 | `in_progress` | this file |
| VALR-T22 | [#327](https://github.com/6spot/Loom/issues/327) | #325 / T20 | `done` / re-review in progress | `t22-certification-manifest.md` (T22-owned; PR #377 is historical snapshot evidence) |
| VALR-T23 | [#328](https://github.com/6spot/Loom/issues/328) | #327 / T22 | `backlog` | `t23-core-integrated-gate.md` (T23-owned; no `103a75e…` current-main evidence) |
| VALR-T24 | [#329](https://github.com/6spot/Loom/issues/329) | #327 / T22 | `backlog` | `t24-validator-certification-gate.md` (T24-owned; no `103a75e…` current-main evidence) |
| VALR-T25 | [#330](https://github.com/6spot/Loom/issues/330) | #326, #328, #329 | `backlog` | `t25-final-certificate.md` (T25-owned; final certification boundary) |

Current-main V0 re-certification is **pending until T25**. Only T25 may publish
the final certificate after T21, T22, T23 and T24 evidence converges. No root,
Stage, or historical M13 completion claim is changed by this record.

## Acceptance

- [ ] Current status is consistent across README, task index, roadmap and new recertification indexes.
- [ ] Historical M13 candidate/PR/merge evidence remains exact and explicitly historical.
- [ ] Historical Validator ledger `docs/tasks/validator/` remains unchanged and not falsely complete.
- [ ] Stage-3 T21–T25 graph, dependencies, states and stable record references are discoverable.
- [ ] Current-main re-certification remains pending until T25; no V0 re-certified/root-complete claim is made.
- [ ] Documentation/ledger checks and `git diff --check` pass; review/merge evidence is recorded by the Leader workflow.

## Progress Log

- 2026-08-27 — Created the current-main recertification root and Stage-3 navigation, reconciled README/task-index/roadmap status wording, and created this T21 in-progress ledger. Preserved M13 candidate/PR/merge facts, separated post-M13 authority-fix history, left the historical Validator ledger untouched, and kept final certification pending until T25.
- 2026-08-29 — Initial snapshot reconciliation against candidate `4efb1d346c926f2ee10654c3bc24cd92af351881` and evidence snapshot/base `6da9989eb9298aa9739a6aa681fbdb8cd9dcde4d`. Recorded merged T19/T22/T23/T24 snapshot evidence, replaced the superseded `95f7e7...`/pending current-state claims, and retained the prior candidate and non-current evidence as historical. T24 remains blocked by CV-028/CV-029; final certification remains pending until T25.
- 2026-08-29 — D-001 rework: corrected actual `main` to `ef281f886480663a94193f738179d14933040a12` after PR #380, while retaining `6da9989eb9298aa9739a6aa681fbdb8cd9dcde4d` as the evidence snapshot/base and `4efb1d…` as the production candidate. Reclassified T20/T22/T23/T24 results as snapshot evidence with actual-main re-audit pending; preserved all historical evidence and certification/T25 boundaries.
- 2026-08-29 — Current-main update: actual `main` and the T20 evidence baseline advanced to `103a75e96cd9f7b9e495a39bb6608316c47b76e6` through PR #382 merge `a898e5be6e33f5f448992c7ddb642af7336bc8f8`, PR #383 merge `7e92033c5b3a14ea30ad8b18bbc68f73145866bb` and PR #384. T20 is refreshed with 10/10 trusted PG18 evidence; T22 is under parallel re-review; T23/T24/T25 have no current-main evidence. Former PR #381, `4efb1d…`, `6da9989…` and `ef281f8…` records remain historical/superseded.

## Historical verification evidence (superseded 2026-08-29 snapshot)

- `PYTHONDONTWRITEBYTECODE=1 python3 tools/test_validator_ready.py` — PASS;
  3 contract tests passed, 0 failed.
- `PYTHONDONTWRITEBYTECODE=1 python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json` — FAIL/expected non-terminal aggregate;
  current graph and owner records retain in-progress/blocked dependencies, so
  this is not evidence of certification.
- `PYTHONDONTWRITEBYTECODE=1 python3 tools/validator_ready.py --check --format json` — PASS;
  canonical historical Validator ledger returned `valid: true` and
  `violations: []` (`record_count: 10`).
- `PYTHONDONTWRITEBYTECODE=1 python3 tools/validator_ready.py --root docs/tasks/validator-recert/stage-1 --check --format json` — PASS;
  Stage-1 ledger returned `valid: true` and `violations: []`
  (`record_count: 7`).
- `python3 tools/check_architecture.py` — PASS; architecture dependency policy
  and storage SQL ownership checks passed.
- T21 documentation/status snapshot assertions — PASS; current candidate,
  exact PR/merge/CI references, historical/non-current labels, preserved M13
  and blocked-CV facts, pending-T25 boundary, and local Markdown links were
  checked against this candidate.
- `git diff --check` — PASS; no whitespace errors in the candidate diff.

## Superseded verification evidence (2026-08-29 ef snapshot)

The reconciliation was checked against actual `main` at
`ef281f886480663a94193f738179d14933040a12`, with snapshot/base
`6da9989eb9298aa9739a6aa681fbdb8cd9dcde4d` and candidate
`4efb1d346c926f2ee10654c3bc24cd92af351881` kept distinct. Before commit, the
working-tree diff was limited to the six T21-owned/index documents named in the inventory;
no T15/T19/T22/T23/T24 ledger, production/Validator API, manifest, registry,
acceptance, or T25 file changed.

- `PYTHONDONTWRITEBYTECODE=1 python3 tools/test_validator_ready.py` — PASS;
  3 tests passed.
- `PYTHONDONTWRITEBYTECODE=1 python3 tools/validator_ready.py --check --format json` — PASS;
  historical Validator ledger `valid: true`, 10 records, no violations.
- `PYTHONDONTWRITEBYTECODE=1 python3 tools/validator_ready.py --root docs/tasks/validator-recert/stage-1 --check --format json` — PASS;
  Stage-1 ledger `valid: true`, 7 records, no violations.
- `PYTHONDONTWRITEBYTECODE=1 python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json` — expected non-terminal FAIL;
  `valid: false` because unchanged owner-ledger metadata still reports T19/T20
  dependency eligibility and T24's missing T22 task metadata. This is retained
  as a governance dependency result, not converted to a certification Pass;
  the forbidden sibling ledgers are not modified by T21.
- `python3 tools/check_architecture.py` — PASS; architecture dependency policy
  and storage SQL ownership checks passed.
- `python3 tools/check_storage_sql_ownership.py` — PASS.
- `git diff --check` — PASS.

PR #380 was independently verified as merged (head
`3abc7f65d21fe7d6564c671ab18db11420da3741`, base `6da9989…`, merge
`ef281f8…`, required CI successful). Its production changes are outside this
T21 diff; no T20/T22/T23/T24 re-audit was run here, so their snapshot evidence
is not promoted to actual-main evidence.

Completion fields remain blank until the Leader's merge workflow supplies
completion PR and merge evidence.

## Latest verification evidence (2026-08-29 current-main update)

The reconciliation update was checked against actual `main` and T20 evidence
baseline `103a75e96cd9f7b9e495a39bb6608316c47b76e6`. The earlier PR #381,
candidate `4efb1d…`, snapshot/base `6da9989…` and prior actual-main
`ef281f8…` remain historical/superseded; the six-file diff is limited to this
T21/index scope and does not rewrite any owner ledger.

- `PYTHONDONTWRITEBYTECODE=1 python3 tools/test_validator_ready.py` — PASS;
  3 tests passed.
- `PYTHONDONTWRITEBYTECODE=1 python3 tools/validator_ready.py --check --format json`
  — PASS; historical Validator ledger `valid: true`, 10 records, no violations.
- `PYTHONDONTWRITEBYTECODE=1 python3 tools/validator_ready.py --root docs/tasks/validator-recert/stage-1 --check --format json`
  — PASS; Stage-1 ledger `valid: true`, 7 records, no violations.
- `PYTHONDONTWRITEBYTECODE=1 python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json`
  — expected non-terminal FAIL/`valid: false`; unchanged T19/T20/T21
  dependencies and T24's missing T22 task metadata remain reported. This is
  not promoted to Pass and no sibling ledger is changed by T21.
- `python3 tools/check_architecture.py` — PASS; architecture dependency policy
  is OK and the storage SQL ownership check passed.
- `python3 tools/check_storage_sql_ownership.py` — PASS.
- T21 current-main/lineage/historical/pending assertions — PASS.
- `git diff --check origin/main...HEAD` — PASS; forbidden-path scan — EMPTY.
- T25 was not rerun; CV-028/CV-029 were not represented as Pass.
