---
task: SCHD-T17
issue: 419
status: completed
depends_on: [418]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at: 2026-08-31
completion_pr: 457
merge_sha: 6a4279e63273b8a53742af8c118e984ebd93f07b
---

# SCHD-T17 — Rewrite quickstart/operator guidance for automatic Scheduler discovery

## Goal

Align active user/operator documentation with one-command deployment and
automatic discovery.

## Scope and acceptance

- [x] Update Scheduler/deployment sections in `docs/quickstart.md`,
      `docs/operator-guide.md` and only directly relevant active `README.md`
      prose.
- [x] Describe `docker compose up -d`, server-lifecycle supervision and
      automatic discovery of new/forked Timelines with Pending Work.
- [x] State that PostgreSQL remains authority and Supervisor discovery does not
      choose logical Work ordering; retain accurate blocked Work, Chronology
      Budget and Runtime Revision semantics.
- [x] Remove instructions to set target IDs or force-recreate for activation;
      document only existing poll/limit tuning.
- [x] Documentation links/checks and CI pass; no speculative bus, pool,
      bootstrap or multi-instance tutorial is added.

## Progress Log

- 2026-08-31 — Post-merge completion audit: delivery PR #457 merged as
  `6a4279e63273b8a53742af8c118e984ebd93f07b`; active documentation and its
  acceptance evidence are reconciled here.

## Verification Evidence

- Active deployment documentation scan and `docker compose -f compose.yaml
  config --quiet` — passed; active docs contain no target-ID activation
  contract and retain only existing poll/limit tuning.
- PR #457 CI run `33334223399` — Classify changes, Active deployment
  documentation, Task ledger governance, Dependency and security policy, Rust
  checks, PostgreSQL 18 persistence contract and Compose config all passed.
