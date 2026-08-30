# Current-main V0 Validator Re-certification

Status: **completed** — the post-M13 Validator trust/coverage initiative has
finished and the final current-main V0 certificate is published.

Root issue: VALR-R0 / GitHub [#302](https://github.com/6spot/Loom/issues/302)

## Final certified baseline

- Certified production candidate:
  `02c55a6b5c34f227abfcb732a21bf6c390e22578` (PR #393 merge).
- Final certificate: [`stage-3/t25-final-certificate.md`](stage-3/t25-final-certificate.md).
- Certificate publication PR: #396, merge
  `c443091783e5a49a0e280366bb85129af536a0bb`.
- Publication CI: run `33290933514`, Rust checks success and PostgreSQL 18
  persistence contract success.
- Final Validator certification: **40 Pass / 0 Fail / 0 Unavailable / 0 gap**,
  `gate_passes=true`.
- Required-live evidence: real PostgreSQL 18 execution; no required row is
  certified from skip, environment inference, or unavailable status.

## Completed initiative graph

```text
Stage 1 / #303
  T01..T07 completed
  -> trustworthy Validator evidence/selection/restart/required-live semantics

Stage 2 / #304
  T08..T20 completed
  + T27 completed for the sanctioned derived-resource read boundary
  -> broad V0 public-surface coverage + PostgreSQL 18 live gate

Stage 3 / #305
  T21 completed
  T22 completed: 40 ready / 0 gap
  T23 completed: integrated core + PostgreSQL 18 gate
  T24 completed: 40/40 trustworthy Validator certification
  T25 completed: final current-main V0 certificate

#330 T25 completed
  -> #305 and #302 eligible for closure
```

## Stage status

| Stage | Tracker | State | Key evidence |
| --- | ---: | --- | --- |
| Stage 1 — evidence integrity | #303 | `completed` | T01..T07 ledgers; T07 authority regression gate |
| Stage 2 — public-surface coverage | #304 | `completed` | T08..T20 plus T27; T20 PostgreSQL 18 live matrix |
| Stage 3 — current-main certification | #305 | `completed` | T21..T25; PRs #394/#395/#396 |
| Root — trust closure + V0 recertification | #302 | `completed` | final T25 certificate |

All executable leaf records under `stage-1/`, `stage-2/`, and `stage-3/` have
durable completion metadata or an explicit historical/cancelled disposition.
The full `docs/tasks/validator-recert` Task Graph is checked by CI.

## Final evidence chain

1. **T27 / PR #393** — Architecture Amendment 0004 and the minimal read-only
   public observation boundary for semantic projection and exact blob reads.
   Merge: `02c55a6b5c34f227abfcb732a21bf6c390e22578`; exact-head CI run
   `33269628735` passed.
2. **T22/T23 / PR #394** — final 40-CV manifest and integrated core evidence.
   Merge: `b225d9c36662432bc4f377d8d4f29d0f1ed763fa`; CI run `33288294125`
   passed both required jobs.
3. **T24 / PR #395** — fail-closed final Validator certification gate.
   Merge: `411e5bf7c573d39d1e6ec9fc7ddfed4a3f4d6901`; CI run `33290303853`
   passed. Canonical T24 artifact reports 40/40 Pass and no manifest gap.
4. **T25 / PR #396** — durable final certificate publication.
   Merge: `c443091783e5a49a0e280366bb85129af536a0bb`; CI run `33290933514`
   again passed the full Rust, T24 40-CV, rustdoc, and PostgreSQL 18 gates.

## CV-028 / CV-029 final disposition

The final two historical capability gaps are closed by T27 / PR #393 under
Architecture Amendment 0004. The product expansion is limited to two read-only
Query operations:

- provider-neutral semantic-projection read;
- exact immutable blob-reference read with integrity verification.

No projection mutation/admin API, blob mutation/list/browse API, Storage/SQL
handle, provider SDK type, or alternate World authority was introduced.
Controlled Validator fixture mutation/fault injection remains test-driver setup;
formal capability observations use `LoomClient`.

## Historical evidence boundary

Historical records are preserved and remain truthful for their own candidates.
Nothing in this completion rewrites them into later Pass evidence.

This includes:

- M13 candidate `52905862f3c26a6fb4d9991da2aa9fe8cfd11bc2`, PR #283 integration
  `19c797d3e1e8bd20a21cda419789793623c5ca1f`, and M13-T2 merge
  `dca5463a341bcb4cde19a999eba8ef37e0ea60dd`;
- earlier post-M13 `31 Pass / 9 Unavailable` snapshots;
- the pre-Amendment-0004 `38 Pass / 2 Unavailable` T24 result;
- the old `103a75e96cd9f7b9e495a39bb6608316c47b76e6` evidence snapshot;
- historical PR #380 and cancelled T26.

The owning leaf ledgers retain their detailed chronology. The final certificate
does not reuse those older non-pass snapshots as current evidence.

## Closure checklist

- [x] Validator single-pass/selection/strict/fail-closed evidence semantics are
  repaired and regression-gated.
- [x] Trusted backend/restart/required-live identity semantics are enforced.
- [x] V0 public-surface coverage is mapped to exactly CV-001..CV-040.
- [x] CV-028/CV-029 have sanctioned formal public read observations.
- [x] The final manifest records 40 ready / 0 gap.
- [x] Integrated core evidence is green for the fixed production candidate.
- [x] Final Validator certification records 40/40 Pass.
- [x] Required PostgreSQL 18 evidence is real execution.
- [x] Historical evidence remains historical.
- [x] Final certificate is published with durable PR/merge/CI evidence.
- [x] Full recert Task Graph governance is enforced in CI.

After the final reconciliation PR containing this index completes CI and merges,
GitHub issues #392, #330, #303, #304, #305 and #302 can be closed as completed.
No production or certification work remains behind those issue closures.
