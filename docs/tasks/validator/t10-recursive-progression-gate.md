---
task: VAL-T10
issue: 262
status: planned
depends_on: [260, 261]
created_at: 2026-08-25
started_at:
completed_at:
completion_pr:
merge_sha:
---
# VAL-T10 — Recursive READY-leaf progression and integrated validator gate

Codify the read-only decision rule used by a development workflow to expose
the next validator leaf after a normal completion. The workflow refreshes
repository/GitHub task metadata before running the enumerator; the enumerator
itself is deterministic from the task records it receives.

## READY rule

A record is a READY leaf exactly when all of these facts hold:

1. it is a leaf record (not a tracker/parent/root) and its status is open;
2. every value in `depends_on` resolves to a task record whose status is
   `completed`;
3. neither `architecture_decision_blocker` nor `architecture_blocker` is
   truthy in its front matter.

An unresolved dependency and a cancelled dependency are blockers. A validator
finding is not a dependency or a task-state transition, so it does not remove
an unrelated leaf from READY. The enumerator never appends findings, changes a
status, closes a tracker, or creates remediation work.

## Normal progression loop

```text
enumerate READY → select a READY leaf → implement
→ run standard/related validator scenarios → append durable evidence/findings
→ complete the leaf through the normal task workflow → enumerate READY again
```

The final step is a fresh read of metadata, so completing one leaf exposes its
dependent leaf and any independent parallel branch without replanning. When
all children of a tracker are `completed`, the report marks that tracker
`eligible_for_reconciliation`; the owning workflow performs the close/reconcile
operation. When every child tracker under root `#248` is `completed`, root `#248`
is likewise eligible. These are observations, not automatic mutations.

## Command and fixture

From the repository root:

```bash
python3 tools/validator_ready.py
python3 tools/validator_ready.py --format json
python3 tools/test_validator_ready.py
```

The fixture test exercises two serial leaves (`VAL-A → VAL-B`), a parallel
branch (`VAL-C` and `VAL-D`), a later dependent leaf (`VAL-E`), a recorded
architecture blocker, a finding that leaves unrelated READY leaves eligible,
and tracker/root reconciliation eligibility. It only mutates temporary copies
of fixture records during the test.

## Integrated validator gate

The integrated base validator remains the public-consumer runner and covers
`CV-001`..`CV-009` from the merged ME-260/ME-261 baseline:

```bash
cargo run -q -p loom-validator -- --all
cargo test -p loom-validator --all-features
```

PostgreSQL evidence is explicit: with no `LOOM_TEST_POSTGRES_URL`, the backend
harness reports a missing prerequisite rather than a pass; with a configured
but unreachable endpoint it reports unavailable; strict/required-live policy
cannot pass without live PostgreSQL evidence. The focused contract is covered
by `backend::tests::missing_postgres_url_is_a_prerequisite_not_a_ready_context`.

## Acceptance

- [ ] READY calculation is deterministic from declared metadata;
- [ ] normal completion exposes next eligible leaf(s) on recomputation;
- [ ] recorded scenario failure does not block unrelated READY leaves;
- [ ] tracker/root reconciliation rules are documented and exercised;
- [ ] integrated `CV-001`..`CV-009` supported subset reports deterministic
  outcomes and explicit PostgreSQL prerequisite/unavailable states;
- [ ] Task Ledger evidence confirms no automatic remediation/task-state
  mutation by the validator;
- [ ] fmt/check/clippy/tests and relevant Linux CI gates pass.

## Progress Log

- 2026-08-25 — Added the read-only `tools/validator_ready.py` metadata
  enumerator, deterministic serial/parallel fixture tests, tracker/root
  reconciliation reporting, and integrated validator/prerequisite commands.
- 2026-08-26 — Governance reconciliation (ME-263): `in_progress` while `VAL-T9` (`261`) was `in_progress` violates dependency eligibility (`VAL-T10` depends on `VAL-T9`). Status reverted to `planned` so downstream remains blocked until `VAL-T8` and `VAL-T9` are `completed` under the canonical task graph. Real-ledger validation now runs in CI via `tools/validator_ready.py --check`.
