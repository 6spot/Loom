# Stage 3 — Current-main V0 re-certification

Status: **in_progress** — Stage 3 reconciles repository status and then runs
the current-main certification gates. Its final certification boundary remains
pending until T25; Stage 3 and the recertification root are not complete.

Tracker: VALR-S3 / GitHub [#305](https://github.com/6spot/Loom/issues/305)

## Dependency graph

```text
#325 T20 [done; PR #359, merge 8761991c; current rerun pending]
  ├─> #326 T21 [in_progress] ───────────────────────┐
  └─> #327 T22 [done; PR #366, merge 7cd6844f]         │
             ├─> #328 T23 [in_progress; current rerun pending] ─────────────┤
             └─> #329 T24 [in_progress; current rerun pending] ─────────────┤
                                                     └─> #330 T25 [blocked; final gate]
```

T21 and T22 are the independently unlocked Stage-3 entry leaves. T23 and T24
depend on T22 and may run in parallel after its completion. T25 depends on T21,
T23 and T24 and owns the final current-main certificate and root-close trigger.

## Leaf records

| Class | Task | Issue | Current state | Dependency | Stable record |
| --- | --- | ---: | --- | --- | --- |
| root A | VALR-T21 — status reconciliation | [#326](https://github.com/6spot/Loom/issues/326) | `in_progress` | #325 / T20 | [`t21-status-reconciliation.md`](t21-status-reconciliation.md) |
| root B | VALR-T22 — certification manifest | [#327](https://github.com/6spot/Loom/issues/327) | `done` | #325 / T20 | `t22-certification-manifest.md` (T22-owned); PR #366 merged at `7cd6844ff3459b5dad200a2807c452ad70195efc` |
| gate A | VALR-T23 — full core integrated gate | [#328](https://github.com/6spot/Loom/issues/328) | `in_progress` | #327 / T22 | `t23-core-integrated-gate.md` (T23-owned); old candidate evidence is historical/non-current |
| gate B | VALR-T24 — Validator certification gate | [#329](https://github.com/6spot/Loom/issues/329) | `in_progress` | #327 / T22 | `t24-validator-certification-gate.md` (T24-owned); old candidate evidence is historical/non-current |
| final gate | VALR-T25 — final current-main certificate | [#330](https://github.com/6spot/Loom/issues/330) | `blocked` | #326, #328, #329 | `t25-final-certificate.md` (T25-owned) |

The Stage-2 gate dependency is the completed T20 issue baseline: PR #359
merged at `8761991c36c07b7ee32d2643228bfb458fdeb2d0`. T20's own historical
ledger record is not rewritten by T21.

## Current-main candidate snapshot

The current production candidate under recertification is
`95f7e7a0233cfa917d0c9656b990fd2af4996874`, the PR #365 merge. The integration
`main` currently advances at `8031d1df0a6512a651979c60e2e8e7ef31f08139`, which
is the rebased PR #368 base and does not change the production-candidate
identity for this recertification snapshot. CV-017's public ingress-recovery
evidence is present on the candidate, but the Stage-3 certification inputs have
not converged on it. T20 has no fresh
terminal rerun recorded. T22's refresh is merged by PR #366 at
`7cd6844ff3459b5dad200a2807c452ad70195efc` (base
`95f7e7a0233cfa917d0c9656b990fd2af4996874`, head
`5dbe09bbdbc5f1c309dd59d96e1579c5b4125f34`); its CI run `33159634407` has
both required checks terminal SUCCESS, and the manifest is consumed as an
evidence-only descendant. T23 and T24 have no complete current-main rerun
recorded. Their merged PRs #363 and #362, their
`34fc8efa77cf61d8a9261eaec575bbe111615618` candidate evidence, and the old
`31 Pass / 9 Unavailable` with `gate_passes: false` remain
historical/non-current evidence.

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
