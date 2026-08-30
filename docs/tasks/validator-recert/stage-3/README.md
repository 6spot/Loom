# Stage 3 — Current-main V0 re-certification

Status: **completed** — T21 through T25 are complete and the final certificate
is published. Stage 3 now has no remaining executable work.

Tracker: VALR-S3 / GitHub [#305](https://github.com/6spot/Loom/issues/305)

## Certified baseline

- Production candidate: `02c55a6b5c34f227abfcb732a21bf6c390e22578`
  (PR #393 merge).
- Final certificate publication: PR #396, merge
  `c443091783e5a49a0e280366bb85129af536a0bb`.
- Certificate publication CI: run `33290933514`, both required jobs success.
- Final Validator result: **40 Pass / 0 Fail / 0 Unavailable / 0 gap**,
  `gate_passes=true`.
- Required PostgreSQL evidence: real PostgreSQL 18 execution, including the T20
  live matrix and the full persistence contract.

## Completed dependency graph

```text
#325 T20 [completed]
  |-> #326 T21 [completed; PR #385]
  \-> #327 T22 [completed; PR #394]
             |-> #328 T23 [completed; PR #394]
             \-> #329 T24 [completed; PR #395]

#326 + #328 + #329
  -> #330 T25 [completed; PR #396]
```

## Leaf records

| Task | Issue | State | Durable evidence |
| --- | ---: | --- | --- |
| VALR-T21 — status reconciliation | #326 | `completed` | PR #385, merge `4b134f391c307915da28df5846108210467dd1e3`, CI `33251875589` |
| VALR-T22 — certification manifest | #327 | `completed` | PR #394, merge `b225d9c36662432bc4f377d8d4f29d0f1ed763fa` |
| VALR-T23 — full core integrated gate | #328 | `completed` | PR #394, CI `33288294125` |
| VALR-T24 — Validator certification gate | #329 | `completed` | PR #395, merge `411e5bf7c573d39d1e6ec9fc7ddfed4a3f4d6901`, CI `33290303853` |
| VALR-T25 — final current-main certificate | #330 | `completed` | PR #396, merge `c443091783e5a49a0e280366bb85129af536a0bb`, CI `33290933514` |

## Final evidence disposition

T22 represents exactly CV-001..CV-040 and records 40 ready / 0 gap. T23
provides the integrated core and PostgreSQL 18 gate evidence. T24 independently
executes the trustworthy Validator certification gate and records all 40 CVs as
Pass. T25 publishes the final certificate and explicitly records residual gaps
as none.

CV-028/CV-029 are closed by T27 / PR #393 under Architecture Amendment 0004.
Their acceptance observations use the formal `LoomClient` read boundary while
controlled fixture operations remain setup/fault drivers only.

## Historical evidence boundary

Historical evidence is preserved in the owning ledgers and is not rewritten by
this completion state. This includes the M13 candidate and integration records,
the earlier `31 Pass / 9 Unavailable` snapshots, the pre-Amendment-0004
`38 Pass / 2 Unavailable` T24 result, the old `103a75e…` evidence snapshot, and
historical PR #380 / cancelled T26.

Those records remain valid descriptions of their own older candidates. They are
not used as substitutes for the final certificate on
`02c55a6b5c34f227abfcb732a21bf6c390e22578`.

## Tracker closure

All Stage-3 child leaves are complete with durable evidence. GitHub tracker
#305 is eligible for closure after this final reconciliation change is green
and merged; closing the tracker does not alter any certification evidence.
