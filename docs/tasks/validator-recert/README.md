# Current-main V0 Validator Re-certification

Status: **blocked at VALR-T25** — the post-M13 authority/evidence remediation,
current-main manifest, core gate, PostgreSQL 18 gate and trustworthy Validator
gate are implemented and recorded. Final current-main V0 re-certification is
not green because `CV-028` and `CV-029` still lack required formal LoomClient
observables. The recertification root remains open.

Parent tracker: VALR-S3 / GitHub [#305](https://github.com/6spot/Loom/issues/305)

## Current certification decision

The durable final decision is
[`stage-3/t25-final-certificate.md`](stage-3/t25-final-certificate.md).
It deliberately records an architecture-decision blocker rather than adding
public interfaces or promoting internal Runtime/Storage evidence to a
Validator Pass.

Production candidate under evaluation:
`103a75e96cd9f7b9e495a39bb6608316c47b76e6` (PR #384 merge).

Current evidence chain:

| Task | Issue | Current evidence | Disposition |
| --- | ---: | --- | --- |
| T20 PostgreSQL live gate | #325 | PR #384 merge `103a75e96cd9f7b9e495a39bb6608316c47b76e6`; CI `33250772703` | 10/10 trusted PostgreSQL 18 rows Pass |
| T21 status reconciliation | #326 | PR #385 merge `4b134f391c307915da28df5846108210467dd1e3` | complete |
| T22 certification manifest | #327 | PR #386 merge `322a9268648d243abd6196f508f5c88681c0c6a1` | 38 ready / 2 blocking gaps |
| T23 core integrated gate | #328 | PR #388 merge `7334c1ec10ac994546ffabe373abcdf0f023a154`; CI `33264160549` | PASS; gaps retained honestly |
| T24 Validator gate | #329 | PR #387 merge `f0cf50061b31e9f5e5a595ddaa9c71a4eff554d2`; CI `33262635979` | 38 Pass / 2 Unavailable; `gate_passes=false` |
| T24 completion reconciliation | #329 | PR #389 merge `f7644e1421bebf11f09ae16487a6ac3824258a4b`; CI `33267041890` | durable completion metadata reconciled |
| T25 final decision | #330 | `stage-3/t25-final-certificate.md` | **BLOCKED; no green certificate** |

The Stage-3 evidence commits after `103a75e…` are reviewed evidence/governance
descendants. They do not silently redefine the production candidate.

## Remaining blockers

Exactly two current manifest rows block final certification.

### CV-028 — semantic projection

The controlled T15 fixture already drives Runtime-owned semantic projection
registration, query, delete and rebuild while public History/Facet/Timeline
reads prove authoritative World Truth is unchanged. What is missing is an
**existing formal semantic-projection observable through LoomClient**. T08
forbids internal Runtime projection state or SQL from being used as Validator
acceptance evidence.

### CV-029 — blob/reference fetch

The controlled T15 fixture already creates BlobRefs and drives present,
missing and corrupt BlobStore behavior while public Facet/History observations
prove authority is unchanged. What is missing is an **existing formal
blob/reference fetch observable through LoomClient**. T08 forbids internal
BlobStore reads or SQL from being promoted to Validator acceptance evidence.

These are therefore formal-observability / architecture-contract blockers, not
unfinished low-level fixture implementation. T25 cannot resolve them by
inventing two ad-hoc product endpoints. An explicit architecture/planning
decision must either define approved formal observables or formally revise the
V0 certification requirement before the affected evidence can be rerun.

## Stage status

| Stage | Tracker | State |
| --- | ---: | --- |
| Stage 1 — authority/evidence remediation | #303 | implementation leaves complete; historical/current evidence retained |
| Stage 2 — coverage/public-surface validation | #304 | implementation leaves complete; T20 current PG18 evidence complete |
| Stage 3 — current-main re-certification | #305 | **open / blocked at T25** |
| Root current-main re-certification | #302 | **open; not eligible for closure** |

The Stage-3 dependency chain is documented in
[`stage-3/README.md`](stage-3/README.md). Root/Stage-3 closure is forbidden
until the two T25 blockers are resolved and the final gate can truthfully turn
green.

## Evidence policy

The current recertification contract keeps three layers separate:

1. **Controlled test driver:** Runtime/Storage/Scheduler/Blob/projection seams
   may create deterministic fixtures and failure conditions.
2. **Formal public observation:** Validator Pass/Fail/Unavailable conclusions
   must be established through formal LoomClient observations.
3. **Architecture/product gap:** if the capability can be driven but no formal
   read can observe the required result, the row stays blocked rather than
   reaching into internals or automatically expanding the public API.

This policy is why CV-017/CV-018/CV-019 and CV-034..CV-037 were implementable
with controlled drivers plus existing formal reads, while CV-028/CV-029 remain
blocked.

## History boundary

Historical M13 release evidence remains immutable audit context:

- M13-T1 / #202 candidate
  `52905862f3c26a6fb4d9991da2aa9fe8cfd11bc2`, integrated by PR #283 at
  `19c797d3e1e8bd20a21cda419789793623c5ca1f`;
- M13-T2 / #203 closure reconciliation at
  `dca5463a341bcb4cde19a999eba8ef37e0ea60dd`.

Earlier recertification candidates, PRs, failures, unavailable rows and
superseded snapshots remain preserved in the individual Stage-1/Stage-2/Stage-3
owner ledgers. Current status summaries never rewrite those historical facts or
use them as substitutes for current-main evidence.
