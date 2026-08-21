---
task: M2-T6
issue: 31
status: in_progress
depends_on: [27, 28, 29, 30]
created_at: 2026-08-21
started_at: 2026-08-21
completed_at:
completion_pr:
merge_sha:
---

# M2-T6 — PostgreSQL Final Parity Gate

## Goal

Prove on one final `main` baseline that PostgreSQL can replace the in-memory persistence adapter without changing the Milestone 1 Runtime contract.

## Revalidation checklist

- [ ] public `loom-api -> Runtime -> Capability -> validation -> PgStorage -> ExecutionResult` vertical slice passes;
- [ ] second invocation reads state from the first PostgreSQL commit;
- [ ] semantic Rejection creates no Event/State change;
- [ ] zero-Effect Event commits as World Truth;
- [ ] true NoChange leaves TimelineVersion unchanged;
- [ ] candidate overlay remains Runtime-owned and unchanged;
- [ ] ownership/schema/causality failures remain pre-commit failures;
- [ ] same-Event structural reference v0 rule is preserved;
- [ ] stale TimelineVersion concurrency yields one commit winner and no partial mutation;
- [ ] Event/State/Work atomicity holds across failure cases;
- [ ] Durable Work lease/retry/fencing semantics match Milestone 1;
- [ ] technical retry leaves World Truth unchanged;
- [ ] zero-Event Work completion persists atomically;
- [ ] Runtime/Storage Cargo DAG remains compliant;
- [ ] SQLx/PostgreSQL types do not leak into public/extension contracts.

## Final gates

- [ ] `python3 tools/check_architecture.py`;
- [ ] `cargo fmt --all -- --check`;
- [ ] `cargo check --workspace --all-targets --all-features`;
- [ ] `cargo clippy --workspace --all-targets --all-features -- -D warnings`;
- [ ] `cargo test --workspace --all-features`;
- [ ] `RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps`;
- [ ] migrations from empty PostgreSQL 18 database;
- [ ] PostgreSQL integration/parity/concurrency suite;
- [ ] required GitHub Actions checks green on the final candidate.

## Completion evidence

- final candidate SHA:
- PR:
- merge SHA:
- CI runs:
- PostgreSQL verification:
- notes:

## Progress log

- 2026-08-21 — Task record created from issue #31; status `planned`.
- 2026-08-21 — Final serial gate started from `main` baseline `fc7dec3cf4b3305590249e79c8cef0e849bd00ac`, after T2/T3/T4/T5 were merged, audited, and their issues closed completed.
