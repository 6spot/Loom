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
| Root [`README.md`](../../../../README.md) | M12/M13 delivery and candidate/closure records are historical; current-main V0 re-certification is in progress and pending until T25. |
| [`docs/tasks/README.md`](../../README.md) | `v0-roadmap.md` is the M4–M13 implementation history; current-main re-certification is separately indexed here and pending until T25. |
| [`docs/tasks/v0-roadmap.md`](../../v0-roadmap.md) | M4–M13 is a historical implementation baseline; its M13 candidate/closure entry is preserved and does not certify current `main`. |
| [`docs/tasks/validator-recert/README.md`](../README.md) | Post-M13 authority/coverage history and Stage 3 are separate from M13; the initiative is in progress and pending until T25. |
| [`stage-3/README.md`](README.md) | T20 unlocks T21/T22; T23/T24 follow T22; T25 is the final current-main certificate gate. |
| Historical [`docs/tasks/validator/README.md`](../../validator/README.md) | Existing Validator initiative and VAL-T1..T10 records remain unchanged and are not marked complete by this recertification tree. |

The inventory is deliberately limited to current-status/governance sources; it
does not rewrite unrelated task evidence or architecture history.

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
| VALR-T22 | [#327](https://github.com/6spot/Loom/issues/327) | #325 / T20 | `in_progress` | `t22-certification-manifest.md` (T22-owned) |
| VALR-T23 | [#328](https://github.com/6spot/Loom/issues/328) | #327 / T22 | `backlog` | `t23-core-integrated-gate.md` (T23-owned) |
| VALR-T24 | [#329](https://github.com/6spot/Loom/issues/329) | #327 / T22 | `backlog` | `t24-validator-certification-gate.md` (T24-owned) |
| VALR-T25 | [#330](https://github.com/6spot/Loom/issues/330) | #326, #328, #329 | `backlog` | `t25-final-certificate.md` (T25-owned) |

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

## Verification evidence

- `PYTHONDONTWRITEBYTECODE=1 python3 tools/test_validator_ready.py` — PASS;
  3 contract tests passed, 0 failed.
- `PYTHONDONTWRITEBYTECODE=1 python3 tools/validator_ready.py --check --format json` — PASS;
  canonical historical Validator ledger returned `valid: true` and
  `violations: []` (`record_count: 10`).
- `PYTHONDONTWRITEBYTECODE=1 python3 tools/validator_ready.py --root docs/tasks/validator-recert/stage-1 --check --format json` — PASS;
  Stage-1 ledger returned `valid: true` and `violations: []`
  (`record_count: 7`).
- `python3 tools/check_architecture.py` — PASS; architecture dependency policy
  and storage SQL ownership checks passed.
- T21 documentation metadata/history/scope assertions — PASS; required files,
  exact T21 front matter, preserved M13 values, pending-T25 boundary, and local
  Markdown links were checked against this candidate.
- `git diff --check` — PASS; no whitespace errors in the candidate diff.

Completion fields remain blank until the Leader's merge workflow supplies
completion PR and merge evidence.
