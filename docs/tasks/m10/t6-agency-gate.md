---
task: M10-T6
issue: 192
status: in_review
depends_on: [187, 188, 189, 190, 191]
created_at: 2026-08-22
started_at: 2026-08-24
completed_at: 2026-08-24
completion_pr: none (Executor constraint)
merge_sha: candidate SHA reported in issue handoff
---
# M10-T6 — Agency final gate

Create a World with visible/hidden data and multiple same-WorldInstant Wakes. Test NoAction, valid Act, semantic Rejected, technical failure and delayed CAS loss; restart before/after claims; fork Pending Wakes; switch compatible Runtime/cognitive revision; inspect provenance.

## Assertions
- [x] Hidden authoritative data is inaccessible.
- [x] Wake obeys logical head/due/order/chronology and restart/fork.
- [x] NoAction + semantic Rejected complete Wake without fake Events; rejection cannot block forever.
- [x] Act uses normal Action authority.
- [x] Technical failure bounded; missing cognitive software consumes no attempt.
- [x] CAS has one logical winner and explicit reuse/resample evidence.
- [x] Event→Session→revision/executor/context provenance survives restart.
- [x] Same-instant Wake execution demonstrates Timeline serialization, not arbitrary write parallelism.
- [x] Standard + PostgreSQL/server Agency gates pass.

## Verification evidence

### AC-to-evidence mapping

- `AC-1` visibility-limited cognition → `crates/loom-storage/src/tests.rs::m10_agency_gate_covers_visibility_order_restart_fork_revision_and_provenance` seeds visible and hidden authoritative Facets, admits only the visible Facet through `AgentWorldViewBuilder`, and verifies the deterministic executor receives no hidden entry.
- `AC-2` deterministic Wake schedule/order/restart/fork → the same gate schedules six same-`WorldInstant` Wakes through `AdminService`, asserts due/order, forks before claims, restarts Runtime before the first claim, and proves the fork retains six Pending Wakes after parent execution.
- `AC-3` NoAction/rejection completion → existing `agency_no_action_completes_wake_without_world_event` and `agency_semantic_rejection_completes_wake_without_fake_event`, plus the final gate's R2 rejection assertion.
- `AC-4` normal Act authority → existing `agency_act_reuses_action_authority_and_commits_atomically`, plus the final gate's R2 `EVENT_ACTION` commit and Event↔Session lookup.
- `AC-5` bounded failure/missing cognition → existing technical retry coverage and the final gate's retained technical failure (`attempt_count = 1`) plus missing cognition pre-claim (`attempt_count = 0`).
- `AC-6` CAS winner/reuse policy → existing InMemory/PostgreSQL CAS suites and the final gate's delayed cognition, single cancelled conflict Work, discarded Session and one resampled completion.
- `AC-7` provenance/revision switch → the final gate verifies R1/R2 Session pinning, executor/policy/context evidence, Event→Session and Session→Event references after restart.
- `AC-8` same-instant serialization → the final gate asserts all committed Events use the single pinned `WorldInstant` and ordered Work completion leaves one authoritative Event outcome.

### Commands

- `python3 tools/check_architecture.py` → passed.
- `cargo fmt --all -- --check` → passed.
- `cargo check --workspace --all-targets --all-features` → passed.
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` → passed.
- `cargo test -p loom-storage m10_agency_gate --lib --all-features` → 1 passed.
- `bash tools/test.sh --workspace --all-features` → full workspace, PostgreSQL 18, restart/fork/concurrency, deterministic Agency and server suites passed.
- `RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps` → passed.
