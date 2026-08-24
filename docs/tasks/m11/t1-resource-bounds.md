---
task: M11-T1
issue: 193
status: in_review
depends_on: [192]
created_at: 2026-08-22
started_at: 2026-08-24
completed_at:
completion_pr:
merge_sha:
---
# M11-T1 — Bounded resource policies

- Inventory/configure limits across Action/Event/Work payloads, Resolution/subresolution, Reaction scheduling, chronology, retrieval/history/causal queries, Agent context/cognition, provenance, Ingress, HTTP/SSE and worker concurrency.
- Runtime enforces semantic/execution bounds independently of Boundary; Boundary rejects oversized transport early where practical.
- Server validates unsafe/impossible config and can expose non-secret effective policy.
- Under/exact/over tests prove typed failure and no partial authority mutation.

## Forbidden
No HTTP-only protection, unbounded production recursive/query defaults, silent truncation without cursor contract, or deployment thresholds in Core.

## Acceptance
- [ ] Every amplification path has owner/config/enforcement.
- [ ] Over-limit semantic execution cannot partially commit.
- [ ] Runtime/Boundary independent limit tests pass.
- [ ] Invalid server config fails startup.
- [ ] Standard/integration gates pass.

## Verification evidence

- `cargo fmt --all -- --check`
- `cargo check --workspace --all-targets --all-features`
- `cargo test --workspace --all-features` (all workspace, integration, PostgreSQL and doc tests passed)
- `cargo clippy --workspace --all-targets --all-features -- -D warnings`
- `python3 tools/check_architecture.py`
