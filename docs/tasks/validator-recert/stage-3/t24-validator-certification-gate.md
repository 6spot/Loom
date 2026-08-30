---
task: VALR-T24
issue: 329
status: completed
depends_on: [327]
created_at: 2026-08-27
started_at: 2026-08-30
completed_at: 2026-08-30
completion_pr: 395
merge_sha: 411e5bf7c573d39d1e6ec9fc7ddfed4a3f4d6901
architecture_decision_blocker: false
---

# VALR-T24 — Final Validator certification gate

## Certified production candidate

`02c55a6b5c34f227abfcb732a21bf6c390e22578` — PR #393 merge, containing Architecture Amendment 0004 and the formal read-only semantic-projection / exact-blob Query boundary used by CV-028 and CV-029.

The previous T24 results on older candidates remain historical. In particular, the earlier truthful `38 Pass / 2 Unavailable` result predates Amendment 0004/T27 and is not rewritten or promoted into this certification.

## Final execution evidence

PR #395 merged as `411e5bf7c573d39d1e6ec9fc7ddfed4a3f4d6901`. Its exact branch head was `3a001d9bf13a5ce46724b2790741bbe39be0553b`; GitHub Actions evaluated PR synthetic merge `e8729f1ca35a52f8e623e82187bccdada8853a67` as an evidence-only descendant of the fixed production candidate.

CI run `33290303853` completed successfully on 2026-08-30:

- `Rust checks`: **success** — dependency/security policy, architecture policy, canonical Validator ledger, full re-certification ledger, Stage-1 authority gate, Compose validation, fmt, workspace check, strict Clippy, full workspace tests, T24 certification gate, report upload, and rustdoc all passed.
- `PostgreSQL 18 persistence contract`: **success** — schema/migration, World lifecycle, Template birth, public Runtime/API vertical parity, read/CAS/Durable Work/stale-fence contracts, Runtime restart/resume and Revision contracts, Validator lifecycle/replay-fork live paths, and the T20 live matrix all passed.

The uploaded `validator-t24-final-certification` artifact is artifact id `9725902703`, digest `sha256:2b15838ebd87ce5c69163c9d487d545f29a330108917898ef2f4462ea17b7788`.

Its machine report records:

- `candidate_sha = 02c55a6b5c34f227abfcb732a21bf6c390e22578`;
- merged T22 input at `b225d9c36662432bc4f377d8d4f29d0f1ed763fa`;
- exactly CV-001 through CV-040, deterministic and duplicate-free;
- **40 Pass / 0 Fail / 0 Unavailable**;
- `manifest_gap_count = 0`;
- every one of the 17 underlying command groups had `exit_code = 0` and `tests_executed = true`;
- `gate_passes = true`.

CV-028/CV-029 are certified from the controlled `semantic_blob` suite. Runtime/ProjectionStore/BlobStore are used only to prepare or fault the derived fixture; the capability observations are returned through formal `LoomClient` semantic/blob reads plus authoritative public World reads. They are intentionally not converted into generic-registry mutation scenarios.

## CI ancestry regression and fix

The first #395 run (`33288835226`) correctly passed all ordinary workspace and PostgreSQL tests but the T24 candidate fence failed before certification because the default depth-1 GitHub PR checkout could not prove ancestry through the synthetic merge commit. This was a CI-history error, not a Validator failure.

PR #395 fixed only that execution mechanic by setting the Rust certification checkout to `fetch-depth: 0`. No production code, candidate SHA, scenario, or acceptance criterion changed. Run `33290303853` then passed the ancestry fence and the complete T24 gate.

## Acceptance

- [x] T22 is merged and records 40 ready / 0 gap for the fixed production candidate.
- [x] T23 is completed from PR #394 core/PG18 evidence on an evidence-only descendant.
- [x] T24 tooling fails closed on production-changing descendants.
- [x] Full `docs/tasks/validator-recert` Task Ledger validation is wired into CI.
- [x] T24 report contains exactly 40 Pass, 0 gap, and `gate_passes=true`.
- [x] All underlying commands executed real nonzero tests with no failure.
- [x] Required CI, including PostgreSQL 18 and rustdoc, completed successfully.
- [x] PR #395 merged and durable completion evidence is recorded.
