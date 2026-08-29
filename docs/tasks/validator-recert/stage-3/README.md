# Stage 3 — Current-main V0 re-certification

Status: **in_progress** — Stage 3 reconciles repository status and then runs
the current-main certification gates. Its final certification boundary remains
pending until T25; Stage 3 and the recertification root are not complete.

Tracker: VALR-S3 / GitHub [#305](https://github.com/6spot/Loom/issues/305)

## Dependency graph

```text
#325 T20 [done; PR #359, merge 8761991c; snapshot 4efb1d live matrix 10/10; re-audit pending]
  ├─> #326 T21 [in_progress] ───────────────────────┐
  └─> #327 T22 [done; PR #377, merge 856814df; snapshot evidence; re-audit pending] │
             ├─> #328 T23 [done; PR #376, merge 657e571ce; snapshot evidence] ──────┤
             └─> #329 T24 [blocked; PR #378, merge 7716c1c3; snapshot gap result] ────┤
                                                     └─> #330 T25 [blocked; final gate]
```

T21 and T22 are the independently unlocked Stage-3 entry leaves. T23 and T24
depend on T22 and may run in parallel after its completion. T25 depends on T21,
T23 and T24 and owns the final current-main certificate and root-close trigger.

## Leaf records

| Class | Task | Issue | Current state | Dependency | Stable record |
| --- | --- | ---: | --- | --- | --- |
| root A | VALR-T21 — status reconciliation | [#326](https://github.com/6spot/Loom/issues/326) | `in_progress` | #325 / T20 | [`t21-status-reconciliation.md`](t21-status-reconciliation.md) |
| root B | VALR-T22 — certification manifest | [#327](https://github.com/6spot/Loom/issues/327) | `done` | #325 / T20 | `t22-certification-manifest.md` (T22-owned); PR #377 merged at `856814dfef5ca800e7c94cdabffd926846663110` |
| gate A | VALR-T23 — full core integrated gate | [#328](https://github.com/6spot/Loom/issues/328) | `done` | #327 / T22 | `t23-core-integrated-gate.md` (T23-owned); PR #376 merged at `657e571ced6e06219e9d1a065775d762e4a83279`; 4efb1d snapshot evidence, actual-main re-audit pending |
| gate B | VALR-T24 — Validator certification gate | [#329](https://github.com/6spot/Loom/issues/329) | `blocked` | #327 / T22 | `t24-validator-certification-gate.md` (T24-owned); PR #378 merged at `7716c1c33cd08cde57e8226ca063c6c83c650e8e`; 4efb1d snapshot gap result, actual-main re-audit pending |
| final gate | VALR-T25 — final current-main certificate | [#330](https://github.com/6spot/Loom/issues/330) | `blocked` | #326, #328, #329 | `t25-final-certificate.md` (T25-owned) |

The Stage-2 gate dependency is the completed T20 issue baseline: PR #359
merged at `8761991c36c07b7ee32d2643228bfb458fdeb2d0`. The 10/10 trusted live
matrix recorded by T23 is evidence for candidate `4efb1d…` on snapshot/base
`6da9989…`; it is pending re-audit against actual `main` after PR #380. T20's
own ledger record is not rewritten by T21.

## Current-main candidate snapshot

The production candidate under recertification is
`4efb1d346c926f2ee10654c3bc24cd92af351881`, the PR #375 merge. The T21
evidence snapshot/base is `6da9989eb9298aa9739a6aa681fbdb8cd9dcde4d`; actual
current `main` is `ef281f886480663a94193f738179d14933040a12` after PR #380
(head `3abc7f65d21fe7d6564c671ab18db11420da3741`) added production
semantic/blob API and mediation changes. PRs #376/#377/#378/#379 record
evidence-only results for the snapshot, not actual-main evidence: T20's 10/10
matrix, T22's 38-ready manifest with CV-028/CV-029 gaps, T23's passing core
evidence and T24's fail-closed `gate_passes: false` result all require
re-audit against actual main. The prior `95f7e7a...` candidate, older PRs and
old `31 Pass / 9 Unavailable` result remain historical/non-current evidence.
Current-main V0 re-certification remains **pending until T25**; neither this
Stage-3 index nor its root checklist is closed.

The old CV-017/CV-018/CV-019/CV-028/CV-029/CV-034..CV-037 blocked conclusions
remain preserved in the owner ledgers. Current-main V0 re-certification remains
**pending until T25**; neither this Stage-3 index nor its root checklist is
closed.

## Historical evidence boundary

M13 candidate `52905862f3c26a6fb4d9991da2aa9fe8cfd11bc2`, integration merge
`19c797d3e1e8bd20a21cda419789793623c5ca1f` (PR #283), and M13-T2 merge
`dca5463a341bcb4cde19a999eba8ef37e0ea60dd` remain historical evidence. The
Stage-1/Stage-2 ledgers record post-M13 authority-fix and public-surface work;
neither history is current-main certification until T25 consumes the required
evidence.
