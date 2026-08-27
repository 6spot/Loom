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
| 3A | VALR-T23 — full core integrated gate | [#328](https://github.com/6spot/Loom/issues/328) | `backlog` | T23-owned `stage-3/t23-core-integrated-gate.md`; depends on #327 / T22 |
| 3B | VALR-T24 — Validator certification gate | [#329](https://github.com/6spot/Loom/issues/329) | `backlog` | T24-owned `stage-3/t24-validator-certification-gate.md`; depends on #327 / T22 |
| 3C | VALR-T25 — final current-main certificate | [#330](https://github.com/6spot/Loom/issues/330) | `backlog` | T25-owned `stage-3/t25-final-certificate.md`; depends on #326, #328 and #329 |

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
