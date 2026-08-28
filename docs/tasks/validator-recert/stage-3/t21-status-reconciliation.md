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
| Root [`README.md`](../../../../README.md) | Current candidate is `95f7e7a0233cfa917d0c9656b990fd2af4996874` from merged PR #365; CV-017 is current-main implementation evidence, while T20/T22/T23/T24 certification inputs remain pending/non-current until T25. |
| [`docs/tasks/README.md`](../../README.md) | M4–M13 remains historical; current-main re-certification is separately indexed, with older gate results marked historical/non-current and current reruns pending until T25. |
| [`docs/tasks/v0-roadmap.md`](../../v0-roadmap.md) | M4–M13 is a historical implementation baseline; current candidate `95f7e7a0233cfa917d0c9656b990fd2af4996874` and the pending-T25 boundary are explicit. |
| [`docs/tasks/validator-recert/README.md`](../README.md) | Exact PR/SHA/CI snapshot distinguishes current CV-017 evidence, merged T22 manifest evidence, and pending current-main T20/T23/T24 inputs. |
| [`stage-3/README.md`](README.md) | T20 is issue-done on an older candidate; T22 is done on the current candidate's evidence-only manifest descendant; T23/T24 remain in progress for current-main evidence; T25 is the final gate. |
| Historical [`docs/tasks/validator/README.md`](../../validator/README.md) | Existing Validator initiative and VAL-T1..T10 records remain unchanged and are not marked complete by this recertification tree. |

The inventory is deliberately limited to current-status/governance sources; it
does not rewrite unrelated task evidence or architecture history.

## Current candidate and gate snapshot

The current production candidate under recertification is exactly
`95f7e7a0233cfa917d0c9656b990fd2af4996874` (the PR #365 merge). The integration
`main` currently advances at `8031d1df0a6512a651979c60e2e8e7ef31f08139`, which
is the rebased PR #368 base; this does not change the production-candidate
identity for the snapshot. PR #365's required CI run `33150850081` completed
successfully for both `Rust checks` and `PostgreSQL 18 persistence contract`.
The merged CV-017 implementation and its public recovery tests are current-main
evidence; they do not constitute the final V0 certificate.

| Task | Current status and exact linked-PR state | Current-main evidence disposition |
| --- | --- | --- |
| T20 / ME-296 | Issue `done`; PR #359 merged (`a1d7d3cd274499e613fac70ce57d34e79483e613` → `8761991c36c07b7ee32d2643228bfb458fdeb2d0`, base `4cb890cc4728402ba8dca2ee6131d45bda61a6d9`), CI run `33065369687` passed both required jobs | The clean 10/10 PG18 matrix is tied to that older candidate. No fresh terminal rerun on `95f7e7a0233cfa917d0c9656b990fd2af4996874` is recorded: **pending**. The T20 ledger remains an append-only owner record and is not rewritten here. |
| T22 / ME-298 | Issue `done`; old PR #361 merged (`0e7a9708dfd0a80d2797c164630313cbcd6fd05d` → `34fc8efa77cf61d8a9261eaec575bbe111615618`, base `a4846837979b5da93bd5e193606f4d04a6a32fd5`), CI run `33071669249` passed; current PR #366 merged (`5dbe09bbdbc5f1c309dd59d96e1579c5b4125f34` → `7cd6844ff3459b5dad200a2807c452ad70195efc`, base `95f7e7a0233cfa917d0c9656b990fd2af4996874`), CI run `33159634407` passed both required jobs | The old manifest and its `31 Pass / 9 Unavailable` / `gate_passes: false` result are historical/non-current. The current manifest refresh is merged and consumed as an evidence-only descendant; it does not certify final V0. |
| T23 / ME-299 | Issue `in_progress`; PR #363 merged (`0928f2b7c287d8e5b3cf3be12bf65fdc0a6e66a8` → `6c132cd43e5e7f5f0e5649e938f319f3c1e04197`, base/candidate `34fc8efa77cf61d8a9261eaec575bbe111615618`), CI run `33078992248` passed both required jobs | Its clean-database/core-gate evidence is tied to `34fc8efa77cf61d8a9261eaec575bbe111615618`, not `95f7e7a0233cfa917d0c9656b990fd2af4996874`; no complete current-main rerun is recorded: **pending/in progress**. |
| T24 / ME-300 | Issue `in_progress`; PR #362 merged (`0eb658c838b534c7611a738452fa957dfcf275fc` → `6f22531a909d0becd1d7b30836168f76cd3d5d33`, base/candidate `34fc8efa77cf61d8a9261eaec575bbe111615618`), CI run `33082656482` passed both required jobs | Its Validator gate evidence, including old `31 Pass / 9 Unavailable` and `gate_passes: false`, is tied to `34fc8efa77cf61d8a9261eaec575bbe111615618`, not `95f7e7a0233cfa917d0c9656b990fd2af4996874`; no complete current-main rerun is recorded: **pending/in progress**. |

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
| VALR-T22 | [#327](https://github.com/6spot/Loom/issues/327) | #325 / T20 | `done` | `t22-certification-manifest.md` (T22-owned; PR #366 merged and consumed) |
| VALR-T23 | [#328](https://github.com/6spot/Loom/issues/328) | #327 / T22 | `in_progress` | `t23-core-integrated-gate.md` (T23-owned; current-main rerun pending) |
| VALR-T24 | [#329](https://github.com/6spot/Loom/issues/329) | #327 / T22 | `in_progress` | `t24-validator-certification-gate.md` (T24-owned; current-main rerun pending) |
| VALR-T25 | [#330](https://github.com/6spot/Loom/issues/330) | #326, #328, #329 | `blocked` | `t25-final-certificate.md` (T25-owned; blocked until prerequisite evidence converges) |

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

Completion fields remain blank until the Leader's merge workflow supplies
completion PR and merge evidence.
