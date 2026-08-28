# Current-main V0 Validator Re-certification

Status: **in_progress** — this initiative reconciles post-M13 Validator
authority/coverage evidence with the current `main` checkout. Current-main V0
re-certification remains **pending until T25**; this index does not declare V0
re-certified and does not close the recertification root.

Parent tracker: VALR-S3 / GitHub [#305](https://github.com/6spot/Loom/issues/305)

## History boundary

The M13 release and closure records are preserved as historical evidence:

- M13-T1 / GitHub #202 used historical candidate
  `52905862f3c26a6fb4d9991da2aa9fe8cfd11bc2`, integrated by historical PR #283
  at merge `19c797d3e1e8bd20a21cda419789793623c5ca1f`.
- M13-T2 / GitHub #203 recorded historical checklist/status reconciliation at
  merge `dca5463a341bcb4cde19a999eba8ef37e0ea60dd`.

Those candidate, PR and merge values are append-only historical facts. The
post-M13 authority-fix and public-surface evidence is recorded in the Stage-1
and Stage-2 ledgers below; it is not silently substituted for a current-main
certificate. The historical Validator initiative at
[`docs/tasks/validator/README.md`](../validator/README.md) remains a separate
ledger, with its existing VAL-T1..T10 states unchanged.

## Current-main evidence snapshot

As of 2026-08-28, the current implementation candidate is
`95f7e7a0233cfa917d0c9656b990fd2af4996874`, the merge commit for PR #365
(`ME-287: validate CV-017 ingress failure recovery`). PR #365's two required CI
checks passed. Its public CV-017 recovery evidence is current-main evidence, but
does not by itself certify V0.

The Stage-3 gate records have not yet converged on this candidate:

| Leaf | Issue / linked PR state | Current-main evidence status | Historical/non-current evidence retained |
| --- | --- | --- | --- |
| T20 | ME-296 `done`; PR #359 merged at `8761991c36c07b7ee32d2643228bfb458fdeb2d0`, CI run `33065369687` passed | A fresh required-live rerun on `95f7e7a0233cfa917d0c9656b990fd2af4996874` is pending; no new terminal matrix is recorded | PR #359 head `a1d7d3cd274499e613fac70ce57d34e79483e613`; old clean 10/10 PG18 result |
| T22 | ME-298 `in_progress`; PR #366 open, base `95f7e7a0233cfa917d0c9656b990fd2af4996874`, head `98258a4fe89f118745c534e09b51edcfac4bcde9`; PG18 check passed, Rust check pending | Current-main manifest refresh is pending review/merge and terminal CI | PR #361 merge `34fc8efa77cf61d8a9261eaec575bbe111615618`; old `31 Pass / 9 Unavailable` and `gate_passes: false` |
| T23 | ME-299 `in_progress`; PR #363 merged at `6c132cd43e5e7f5f0e5649e938f319f3c1e04197`, CI run `33078992248` passed | No complete rerun on `95f7e7a0233cfa917d0c9656b990fd2af4996874` is recorded; current gate evidence is pending | Old production candidate `34fc8efa77cf61d8a9261eaec575bbe111615618`, PR #363 head `0928f2b7c287d8e5b3cf3be12bf65fdc0a6e66a8`, including its clean-database result |
| T24 | ME-300 `in_progress`; PR #362 merged at `6f22531a909d0becd1d7b30836168f76cd3d5d33`, CI run `33082656482` passed | No complete rerun on `95f7e7a0233cfa917d0c9656b990fd2af4996874` is recorded; current Validator gate evidence is pending | Old production candidate `34fc8efa77cf61d8a9261eaec575bbe111615618`, PR #362 head `0eb658c838b534c7611a738452fa957dfcf275fc`, including old `31 Pass / 9 Unavailable` / `gate_passes: false` |

The historical CV-017 fault-injection blocker and the historical blocked
conclusions for CV-018, CV-019, CV-028, CV-029, and CV-034..CV-037 remain in
their owner ledgers as historical/non-current records. They are not deleted or
rewritten here. Current-main re-certification remains **pending until T25**;
Stage 3 and the recertification root remain open.

## Re-certification records

The earlier post-M13 work remains discoverable in its existing ledgers:

- Stage 1 authority/evidence history: `stage-1/` (including
  [`t07-authority-gate.md`](stage-1/t07-authority-gate.md)).
- Stage 2 public-surface history: `stage-2/` (including
  [`t20-pg18-live-gate.md`](stage-2/t20-pg18-live-gate.md)).

Stage 3 is the current-main reconciliation and certification sequence:

| Stage | Task | Issue | Current state | Stable record / dependency |
| --- | --- | ---: | --- | --- |
| 3A | VALR-T21 — status reconciliation | [#326](https://github.com/6spot/Loom/issues/326) | `in_progress` | [`stage-3/t21-status-reconciliation.md`](stage-3/t21-status-reconciliation.md); depends on #325 / T20 |
| 3B | VALR-T22 — certification manifest | [#327](https://github.com/6spot/Loom/issues/327) | `in_progress` | T22-owned `stage-3/t22-certification-manifest.md`; depends on #325 / T20 |
| 3A | VALR-T23 — full core integrated gate | [#328](https://github.com/6spot/Loom/issues/328) | `in_progress` | T23-owned `stage-3/t23-core-integrated-gate.md`; depends on #327 / T22; current rerun pending |
| 3B | VALR-T24 — Validator certification gate | [#329](https://github.com/6spot/Loom/issues/329) | `in_progress` | T24-owned `stage-3/t24-validator-certification-gate.md`; depends on #327 / T22; current rerun pending |
| 3C | VALR-T25 — final current-main certificate | [#330](https://github.com/6spot/Loom/issues/330) | `blocked` | T25-owned `stage-3/t25-final-certificate.md`; depends on #326, #328 and #329 |

The issue states above are the current execution graph at this baseline. T23,
T24 and T25 record their backlog stable ledger paths here before their owning
leaves create those files; T21 does not create or pre-complete another task's
record.

## Certification boundary

T25 is the only task that may publish the final current-main certificate after
the T21 governance reconciliation, T22 manifest, T23 core gate and T24
Validator gate converge on one candidate. Until then, a current-main
certificate is pending, the Stage-3 tracker remains open, and the V0
recertification root is not complete.
