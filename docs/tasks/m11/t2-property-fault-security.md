---
task: M11-T2
issue: 194
status: completed
depends_on: [193]
created_at: 2026-08-22
started_at: 2026-08-24
completed_at: 2026-08-24
completion_pr: 267
merge_sha: ccce80e0635bf859a8312c0821021153b50c3f2a
---
# M11-T2 — Property/fault/dependency-security gates

- Add cargo-deny or approved equivalent for advisories/licenses/banned/duplicate dependencies with narrow documented exceptions.
- Deterministic bounded property tests for EventSeq/TimelineVersion, semantic/logical replay, fork isolation/causality, Work order/fence, chronology, Ingress idempotency and Session pinning.
- Fault injection around PostgreSQL commit rollback, Event↔Session, Ingress crash window, scheduler claim/complete/retry, Template birth and fork.
- Preserve reproducible failing seeds/regression cases and serialization/stable-order tests.
- Integrate into long-lived CI only.

## Acceptance
- [x] Security/license/dependency gate reproducible.
- [x] Listed authority invariants have property/fault coverage.
- [x] Failures are locally reproducible; focused scenarios remain.
- [x] CI partition/runtime documented and standard gates pass.

## Verification evidence

The T2 checks are bounded and deterministic. Runtime property cases use the
checked-in default seed `0x4d11200220260825` and 64 cases per invariant; a
reproduction can override it without changing production code:

```text
LOOM_PROP_SEED=0x4d11200220260825 cargo test -p loom-runtime --lib property_fault_security -- --nocapture
PROPTEST_SEED=0x4d11200220260825 cargo test -p loom-runtime --lib property_fault_security -- --nocapture
```

The test-side generator is isolated in `crates/loom-runtime/src/property_fault_security.rs`;
`loom-core` and Runtime production modules do not acquire a random source or a
clock. It covers EventSeq/TimelineVersion continuity and overflow, frozen
Effect success/failure, logical-journal replay, fork ancestry/isolation,
logical Work order, claim-fence monotonicity/stale claims, chronology/retry
thresholds, Ingress key/fingerprint exactly-once behavior, Session pinning,
causal references and JSON round trips/stable order.

Fault evidence remains in the existing deterministic adapter suites rather than
replacing them: InMemory staged-commit rollback and stale CAS are covered by
`staged_commit_does_not_expose_event_before_work_failure` and
`stale_cas_leaves_event_state_and_work_unchanged`; Event↔Session linkage by
`committed_event_has_atomic_bidirectional_session_provenance`; Ingress crash
and unknown-outcome windows by
`ingress_finalization_crash_recovers_without_repeating_authority_mutation` and
`ingress_unknown_outcome_retries_reconciliation_without_dispatching_again`;
scheduler claim/complete/retry and Template birth/fork by the existing
`loom-storage` unit and PostgreSQL contract suites.

The long-lived Ubuntu workflow keeps docs-only changes out of the required Rust
jobs while changes to Rust, Cargo metadata, migrations, tools, Compose or
workflow policy run the normal gates. The Rust job installs cargo-deny `0.18.9`
under the pinned Rust `1.97.1` toolchain and runs all four checks:

```text
cargo deny check advisories bans licenses sources
python3 tools/check_architecture.py
cargo test --workspace --all-features
```

Local evidence on this revision:

```text
cargo test -p loom-runtime --lib                                  # 69 passed
cargo test --workspace --all-features                             # passed, including PostgreSQL suites
cargo deny check bans licenses sources                             # passed
python3 tools/check_architecture.py                                # passed
```

The local preinstalled cargo-deny `0.18.3` cannot parse the current advisory
database's CVSS 4.0 record; CI pins `0.18.9`, which is the first supported
version selected for the authoritative advisory gate. The workspace run above
exercised the configured PostgreSQL suites; the same schema, lifecycle/Template
birth, vertical/read/commit, Work/stale-fence and restart/revision evidence is
collected by the existing `postgres-contract` job. Individual suites can be
replayed locally with, for example,
`bash tools/test.sh -p loom-storage --test postgres_schema -- --nocapture`
after setting `LOOM_TEST_POSTGRES_URL` or starting the managed Compose service.
