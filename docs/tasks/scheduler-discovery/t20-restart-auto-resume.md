---
task: SCHD-T20
issue: 422
status: in_progress
depends_on: [417]
created_at: 2026-08-30
started_at: 2026-08-31
completed_at:
completion_pr:
merge_sha:
---

# SCHD-T20 — Prove restart resumes pending Scheduler obligations without target config

## Goal

Prove persisted Pending obligations are rediscovered and resumed after a real
server boundary restart without a fixed target or persisted in-memory cursor.

## Scope and acceptance

- [ ] Start a real server with controlled PostgreSQL 18 and no target fields,
      create representative Pending Work, then stop/rebuild the boundary while
      preserving PostgreSQL state.
- [ ] Restart with the same normal deployment config, do not copy a cursor or
      inject IDs, and observe recovery/progression through formal public/Admin/
      History surfaces.
- [ ] Verify existing Work lease/fence/retry semantics remain authoritative.
- [ ] Use a real application restart, not reconnect-only substitution; no new
      scheduler state, restart manager, direct SQL assertion or manual drive.

## Progress Log

- 2026-08-31 — Added an integration gate that launches the official loom-server binary twice against the same controlled PostgreSQL state, with no Scheduler target IDs and no cursor transfer between processes. The gate checks pending Work recovery through public/Admin/History/Query surfaces and records distinct process IDs as restart evidence.
- 2026-08-31 — Reviewer rework moved PostgreSQL database provisioning and Work operational setup behind the storage-owned `test-support` fixture/API. The live gate now records claim fence 1, a persisted retry, reclaim fence 2, stale-fence rejection, lease expiry while the first server is stopped, and fresh-server recovery at attempt 3 with exactly one recovered mutation.
- 2026-08-31 — Dependency #417 / ME-324 was verified complete in Multica with GitHub PR #452 merged and its six checks passed. The canonical T15 task-ledger row remains coordinator-owned governance state and is intentionally not modified by this leaf.

## Verification Evidence

- `bash tools/test.sh -p loom-server --test scheduler_restart -- --nocapture --test-threads=1` — PASS against controlled PostgreSQL 18; real restart evidence: distinct PIDs, both clean exits, `first_claim_fence=1`, `retry_attempt=1`, `second_claim_fence=2`, `lease_expired_before_recovery=true`, `recovery_attempt=3`, `history=2->3`, `counter=1->2`, `stale_fence_rejected=true`, `cursor_reused=false`, `scheduler_target_configured=false`.
- `cargo test -p loom-storage --lib -- --test-threads=1` — PASS (65 tests) against a fresh PostgreSQL 18 validation database; the default shared local database has stale fixed parity-fixture rows and is not used as acceptance evidence.
