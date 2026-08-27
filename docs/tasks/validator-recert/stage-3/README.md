# Stage 3 — Current-main V0 re-certification

Status: **in_progress** — Stage 3 reconciles repository status and then runs
the current-main certification gates. Its final certification boundary remains
pending until T25; Stage 3 and the recertification root are not complete.

Tracker: VALR-S3 / GitHub [#305](https://github.com/6spot/Loom/issues/305)

## Dependency graph

```text
#325 T20 [done; PR #359, merge 8761991c]
  ├─> #326 T21 [in_progress] ───────────────────────┐
  └─> #327 T22 [in_progress]                         │
             ├─> #328 T23 [backlog] ─────────────────┤
             └─> #329 T24 [backlog] ─────────────────┤
                                                     └─> #330 T25 [backlog; final gate]
```

T21 and T22 are the independently unlocked Stage-3 entry leaves. T23 and T24
depend on T22 and may run in parallel after its completion. T25 depends on T21,
T23 and T24 and owns the final current-main certificate and root-close trigger.

## Leaf records

| Class | Task | Issue | Current state | Dependency | Stable record |
| --- | --- | ---: | --- | --- | --- |
| root A | VALR-T21 — status reconciliation | [#326](https://github.com/6spot/Loom/issues/326) | `in_progress` | #325 / T20 | [`t21-status-reconciliation.md`](t21-status-reconciliation.md) |
| root B | VALR-T22 — certification manifest | [#327](https://github.com/6spot/Loom/issues/327) | `in_progress` | #325 / T20 | `t22-certification-manifest.md` (T22-owned) |
| gate A | VALR-T23 — full core integrated gate | [#328](https://github.com/6spot/Loom/issues/328) | `backlog` | #327 / T22 | `t23-core-integrated-gate.md` (T23-owned) |
| gate B | VALR-T24 — Validator certification gate | [#329](https://github.com/6spot/Loom/issues/329) | `backlog` | #327 / T22 | `t24-validator-certification-gate.md` (T24-owned) |
| final gate | VALR-T25 — final current-main certificate | [#330](https://github.com/6spot/Loom/issues/330) | `backlog` | #326, #328, #329 | `t25-final-certificate.md` (T25-owned) |

The Stage-2 gate dependency is the completed T20 issue baseline: PR #359
merged at `8761991c36c07b7ee32d2643228bfb458fdeb2d0`. T20's own historical
ledger record is not rewritten by T21.

## Historical evidence boundary

M13 candidate `52905862f3c26a6fb4d9991da2aa9fe8cfd11bc2`, integration merge
`19c797d3e1e8bd20a21cda419789793623c5ca1f` (PR #283), and M13-T2 merge
`dca5463a341bcb4cde19a999eba8ef37e0ea60dd` remain historical evidence. The
Stage-1/Stage-2 ledgers record post-M13 authority-fix and public-surface work;
neither history is current-main certification until T25 consumes the required
evidence.
