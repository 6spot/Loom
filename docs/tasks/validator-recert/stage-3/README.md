# Stage 3 — Current-main V0 re-certification

Status: **blocked at T25** — T21/T22/T23/T24 are complete and their current
candidate evidence has converged. T25 has executed the final decision boundary
and is intentionally kept open because the authoritative manifest still has two
blocking formal-observability gaps: `CV-028` and `CV-029`. Stage 3 and the
recertification root are **not complete** and no green V0 re-certification is
claimed.

Tracker: VALR-S3 / GitHub [#305](https://github.com/6spot/Loom/issues/305)

## Dependency graph

```text
#325 T20 [done; PR #384; candidate 103a75e; PG18 10/10]
  ├─> #326 T21 [done; PR #385]
  └─> #327 T22 [done; PR #386; 38 ready / 2 gaps]
             ├─> #328 T23 [done; PR #388; core gate PASS] ───────┐
             └─> #329 T24 [done; PR #387 + #389 reconciliation] ─┤
                                                                  └─> #330 T25 [BLOCKED]
```

T25 is the only final certification boundary. Its current durable record is
[`t25-final-certificate.md`](t25-final-certificate.md); it records a fail-closed
final decision rather than a green certificate.

## Leaf records

| Class | Task | Issue | Current state | Current evidence |
| --- | --- | ---: | --- | --- |
| root A | VALR-T21 — status reconciliation | [#326](https://github.com/6spot/Loom/issues/326) | `done` | PR #385 merge `4b134f391c307915da28df5846108210467dd1e3` |
| root B | VALR-T22 — certification manifest | [#327](https://github.com/6spot/Loom/issues/327) | `done` | PR #386 merge `322a9268648d243abd6196f508f5c88681c0c6a1`; 38 ready / CV-028, CV-029 gaps |
| gate A | VALR-T23 — full core integrated gate | [#328](https://github.com/6spot/Loom/issues/328) | `done` | PR #388 merge `7334c1ec10ac994546ffabe373abcdf0f023a154`; CI `33264160549` success |
| gate B | VALR-T24 — Validator certification gate | [#329](https://github.com/6spot/Loom/issues/329) | `done` | PR #387 merge `f0cf50061b31e9f5e5a595ddaa9c71a4eff554d2`; 38 Pass / 2 Unavailable; PR #389 reconciles completion metadata |
| final gate | VALR-T25 — final current-main certificate | [#330](https://github.com/6spot/Loom/issues/330) | `in_progress` / architecture blocker | no green certificate; see `t25-final-certificate.md` |

## Candidate and current evidence

The production certification candidate remains
`103a75e96cd9f7b9e495a39bb6608316c47b76e6`, PR #384 merge. The later Stage-3
commits are evidence/governance descendants and do not silently replace the
production candidate.

Current required evidence is:

- T20: repository-controlled PostgreSQL 18 required-live matrix, 10/10 Pass;
- T22: authoritative 40-CV manifest, 38 ready and exactly two blocking gaps;
- T23: full current-candidate core/build/storage/integration evidence PASS;
- T24: trustworthy current-candidate Validator evidence, 38 Pass / 2
  Unavailable, `gate_passes=false`;
- T25: fail-closed final decision, blocked on the same two manifest gaps.

The two blockers are not missing test-driver implementation. T15 already has
controlled Runtime/semantic and BlobStore fixtures. They remain blocked because
T08 requires the capability result itself to be observable through a formal
`LoomClient` read and forbids internal Runtime/Storage state from serving as
Validator acceptance evidence:

1. `CV-028` — no existing formal semantic-projection observable;
2. `CV-029` — no existing formal blob/reference fetch observable.

T25 does not own an architecture decision and therefore does not add ad-hoc
public interfaces simply to make the gate green.

## Closure rule

Stage 3 #305 and Root #302 remain open. They can only be reconciled after an
explicit architecture/planning decision resolves both formal-observability
gaps, affected T22/T24 evidence is rerun under the certification candidate
discipline, and T25 can truthfully publish a green certificate.

## Historical evidence boundary

M13 candidate `52905862f3c26a6fb4d9991da2aa9fe8cfd11bc2`, integration merge
`19c797d3e1e8bd20a21cda419789793623c5ca1f` (PR #283), and M13-T2 merge
`dca5463a341bcb4cde19a999eba8ef37e0ea60dd` remain historical evidence only.
Earlier Stage-3 candidates, snapshots, non-pass rows and gap classifications
remain in their owner ledgers as append-only audit history; none is promoted to
current certification by this status summary.
