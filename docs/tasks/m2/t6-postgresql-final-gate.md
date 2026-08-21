---
task: M2-T6
issue: 31
status: completed
depends_on: [27, 28, 29, 30]
created_at: 2026-08-21
started_at: 2026-08-21
completed_at: 2026-08-21
completion_pr: 44
merge_sha:
---

# M2-T6 — PostgreSQL Final Parity Gate

## Goal

Prove on one final `main` baseline that PostgreSQL can replace the in-memory persistence adapter without changing the Milestone 1 Runtime contract.

## Revalidation checklist

- [x] public `loom-api -> Runtime -> Capability -> validation -> PgStorage -> ExecutionResult` vertical slice passes;
- [x] second invocation reads state from the first PostgreSQL commit;
- [x] semantic Rejection creates no Event/State change;
- [x] zero-Effect Event commits as World Truth;
- [x] true NoChange leaves TimelineVersion unchanged;
- [x] candidate overlay remains Runtime-owned and unchanged;
- [x] ownership/schema/causality failures remain pre-commit failures;
- [x] same-Event structural reference v0 rule is preserved;
- [x] stale TimelineVersion concurrency yields one commit winner and no partial mutation;
- [x] Event/State/Work atomicity holds across failure cases;
- [x] Durable Work lease/retry/fencing semantics match Milestone 1;
- [x] technical retry leaves World Truth unchanged;
- [x] zero-Event Work completion persists atomically;
- [x] Runtime/Storage Cargo DAG remains compliant;
- [x] SQLx/PostgreSQL types do not leak into public/extension contracts.

## Final gates

- [x] `python3 tools/check_architecture.py`;
- [x] `cargo fmt --all -- --check`;
- [x] `cargo check --workspace --all-targets --all-features`;
- [x] `cargo clippy --workspace --all-targets --all-features -- -D warnings`;
- [x] `cargo test --workspace --all-features`;
- [x] `RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps`;
- [x] migrations from empty PostgreSQL 18 database;
- [x] PostgreSQL integration/parity/concurrency suite;
- [x] required GitHub Actions checks green on the final candidate.

## Completion evidence

- final candidate SHA: `af7c1de52a2733e20a8b9285dbc4b0da90e7c188`
- PR: #44
- merge SHA: pending post-merge audit
- CI runs: clean implementation/final-code candidate run `32464761591`; final task-record CI pending
- PostgreSQL verification: `postgres_schema`, `postgres_vertical`, `postgres_read`, `postgres_commit`, `postgres_work`, and `postgres_work_stale_completion` all passed against PostgreSQL 18 in run `32464761591`.
- notes: the final candidate starts from audited prerequisite baseline `fc7dec3cf4b3305590249e79c8cef0e849bd00ac`. `postgres_vertical` directly exercises the public `LoomApi` through Runtime and Capability validation into `PgStorage`, proves a second invocation reads the first durable commit, proves semantic rejection leaves version/history/state unchanged, proves zero-Effect Events remain World Truth, and proves true NoChange leaves TimelineVersion unchanged. Existing workspace composition/validation tests continue to prove Runtime-owned candidate overlay and pre-commit ownership/schema/causality authority; the PostgreSQL commit suite proves same-Event structural references, one-winner Timeline CAS, rollback atomicity, and Work-only/current-Work commit semantics; the PostgreSQL Work suites prove lease/retry/fencing, technical retry World-Truth isolation, and zero-Event completion. The architecture checker and crate dependency graph keep SQLx/PostgreSQL confined to Storage/test infrastructure and out of public/extension contracts.

## Progress log

- 2026-08-21 — Task record created from issue #31; status `planned`.
- 2026-08-21 — Final serial gate started from `main` baseline `fc7dec3cf4b3305590249e79c8cef0e849bd00ac`, after T2/T3/T4/T5 were merged, audited, and their issues closed completed.
- 2026-08-21 — Added `postgres_vertical` as a required PostgreSQL 18 CI step to cover public API/Runtime/PgStorage parity gaps not already directly covered by T2-T5 suites.
- 2026-08-21 — Initial vertical-gate run exposed an over-strong test assertion that a zero-Effect Event must not advance `StateRevision`; Milestone 1 requires the Event to become World Truth while materialized Facets remain unchanged, not a fixed StateRevision. The assertion was corrected without changing Runtime or Storage behavior.
- 2026-08-21 — Clean candidate `af7c1de52a2733e20a8b9285dbc4b0da90e7c188` passed CI run `32464761591`: Ubuntu/macOS Architecture, Format, Check, Clippy, Test and Rustdoc plus PostgreSQL 18 scratch migrations, public vertical parity, read parity, commit/CAS/atomicity, Durable Work and stale-fence regression suites. Acceptance is complete; the real merge SHA will be recorded immediately after merge via audit PR.
