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

As of 2026-08-29, actual current `main` and the current T20 evidence baseline
are `103a75e96cd9f7b9e495a39bb6608316c47b76e6`, the merge commit for PR #384.
The post-rollback lineage is PR #382 merge
`a898e5be6e33f5f448992c7ddb642af7336bc8f8`, PR #383 merge
`7e92033c5b3a14ea30ad8b18bbc68f73145866bb`, then PR #384 (head
`d6654ca09d0c9d46701288054090a9bcbddc31af`). T20's owner ledger records
10/10 trusted PostgreSQL 18 rows on `103a75e…`. T22's existing manifest is
under parallel current-main re-review; T23, T24 and T25 have not produced
current-main evidence on this baseline. The former PR #381 reconciliation
(merged as `c1169d26350c19ff7f0ce05f863eea37a116332f`),
candidate `4efb1d346c926f2ee10654c3bc24cd92af351881`, snapshot/base
`6da9989eb9298aa9739a6aa681fbdb8cd9dcde4d`, prior actual-main
`ef281f886480663a94193f738179d14933040a12` and their T20/T22/T23/T24 results
are retained as historical/superseded evidence; this snapshot is not a
certification decision.

The current graph and evidence disposition are:

| Leaf | Issue / linked PR state | Current-candidate evidence status | Historical/non-current evidence retained |
| --- | --- | --- | --- |
| T19 | ME-295 `done`; PR #379 merged (`f1f36856b6e33d41e59d6cfe81eada39f289b43f` → `6da9989eb9298aa9739a6aa681fbdb8cd9dcde4d`, base `7716c1c33cd08cde57e8226ca063c6c83c650e8e`), CI run `33221134508` passed both required jobs | Historical snapshot remains the verified 32-ID registry/list/group set; CV-018/019/028/029/034..037 remain unregistered gap rows. No current-main re-audit is recorded here. | Prior candidate traces, eight gap explanations and non-pass/readiness records remain in the T19 ledger |
| T20 | ME-296 `done`; PR #384 merged (head `d6654ca09d0c9d46701288054090a9bcbddc31af`, base `7e92033c5b3a14ea30ad8b18bbc68f73145866bb`, merge `103a75e96cd9f7b9e495a39bb6608316c47b76e6`), CI run `33250772703` passed both required jobs | Current-main T20 evidence: 10/10 trusted PostgreSQL 18 rows on `103a75e…`; the T20 owner ledger is not rewritten here. | PR #359 and the former `4efb1d…`/`6da9989…` matrix remain historical/superseded evidence |
| T22 | ME-298 `done` for the existing manifest; PR #377 merged (`d3232672c31a133ca6f5f3172e306ea768259c4c` → `856814dfef5ca800e7c94cdabffd926846663110`, base `657e571ced6e06219e9d1a065775d762e4a83279`), CI run `33190567067` passed both required jobs | Current-main re-review is in progress in parallel; no new `103a75e…` evidence is recorded by T21. The 38-ready/CV-028/CV-029 result remains historical snapshot evidence. | Prior PR #366/#361 traces, old `31 Pass / 9 Unavailable` / `gate_passes: false`, and the existing manifest ledger remain historical/non-current |
| T23 | ME-299 `backlog`; PR #376 merged (`92a2a8eb763976b65f84b889b4de95a9124e6fce` → `657e571ced6e06219e9d1a065775d762e4a83279`, base `4efb1d346c926f2ee10654c3bc24cd92af351881`), CI run `33182385085` passed both required jobs | No current-main evidence exists for `103a75e…`; the prior passing core evidence remains candidate/snapshot evidence only and is not promoted by T21. | Earlier `34fc8efa...` candidate, PR #363, and the former PR #376 result remain historical/non-current |
| T24 | ME-300 `backlog`; PR #378 merged (`5d77ddda808f5594c2efe3b8c169f82814d6898b` → `7716c1c33cd08cde57e8226ca063c6c83c650e8e`, base `856814dfef5ca800e7c94cdabffd926846663110`), CI run `33193706827` passed both required jobs | No current-main evidence exists for `103a75e…`; the former snapshot gate remains fail-closed at 38 `Pass`, 2 `Unavailable` (CV-028/CV-029), `gate_passes: false`, and is not certification. | Prior PR #362/#361 traces, old candidate, and old `31 Pass / 9 Unavailable` / `gate_passes: false` remain historical/non-current |

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
| 3B | VALR-T22 — certification manifest | [#327](https://github.com/6spot/Loom/issues/327) | `done` / current-main re-review in progress | T22-owned `stage-3/t22-certification-manifest.md`; PR #377 remains historical snapshot evidence; depends on #325 / T20 |
| 3A | VALR-T23 — full core integrated gate | [#328](https://github.com/6spot/Loom/issues/328) | `backlog` | T23-owned `stage-3/t23-core-integrated-gate.md`; prior PR #376 evidence is historical; depends on #327 / T22 |
| 3B | VALR-T24 — Validator certification gate | [#329](https://github.com/6spot/Loom/issues/329) | `backlog` | T24-owned `stage-3/t24-validator-certification-gate.md`; prior PR #378 gap result is historical; depends on #327 / T22 |
| 3C | VALR-T25 — final current-main certificate | [#330](https://github.com/6spot/Loom/issues/330) | `backlog` | T25-owned `stage-3/t25-final-certificate.md`; depends on #326, #328 and #329 |

The issue states above are the current execution graph at this baseline. T21
remains in progress; T22's prior manifest is done but its current-main review
is parallel; T23/T24/T25 remain backlog with no `103a75e…` current-main
evidence. T21 does not create or pre-complete another task's record.

## Certification boundary

T25 is the only task that may publish the final current-main certificate after
the T21 governance reconciliation, T22 manifest, T23 core gate and T24
Validator gate converge on one candidate. Until then, a current-main
certificate is pending, the Stage-3 tracker remains open, and the V0
recertification root is not complete.
