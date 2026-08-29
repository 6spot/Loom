---
task: VALR-T23
issue: 328
status: completed
depends_on: [327]
created_at: 2026-08-27
started_at: 2026-08-27
completed_at: 2026-08-30
completion_pr: 388
merge_sha: 7334c1ec10ac994546ffabe373abcdf0f023a154
---

# VALR-T23 — Durable completion metadata

This is the machine-readable Task Ledger completion record for T23. The full,
append-only execution evidence remains in
[`t23-core-integrated-gate.md`](t23-core-integrated-gate.md); this companion
record does not replace, summarize away, or rewrite that evidence.

T23's current-main rerun used production candidate
`103a75e96cd9f7b9e495a39bb6608316c47b76e6`, with the refreshed T22 manifest
as an evidence-only descendant. PR #388 merged the current T23 evidence as
`7334c1ec10ac994546ffabe373abcdf0f023a154`; its evidence head
`8c5ee0f9afda9a5a20c196691af01097e6da5dd4` completed CI run `33264160549`
with conclusion `success`.

The durable T23 result is **core integrated gate PASS**. PostgreSQL 18 contract
and required-live evidence executed against fresh databases and passed; all
recorded non-certifying attempts and the remaining T22 capability gaps are
preserved in the detailed ledger. T23 does not claim final V0 certification and
does not reclassify `CV-028` or `CV-029`.

This separate metadata record is required because the historical
`t23-core-integrated-gate.md` evidence ledger predates the frontmatter-based
Task Graph reader and intentionally remains append-only. The Task Graph may use
this record to resolve issue/task alias `#328` / `VALR-T23` as completed while
retaining the detailed evidence file unchanged.
