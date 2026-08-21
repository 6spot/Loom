---
task: M3-T4
issue: 51
status: completed
depends_on: [48, 49, 50]
created_at: 2026-08-21
started_at: 2026-08-21
completed_at: 2026-08-21
completion_pr: 57
merge_sha: 060993b4935dcf92e99226cb50ee22303fda7ecb
---

# M3-T4 — World Lifecycle / Resumability Final Parity Gate

## Goal

Revalidate one final M3 candidate proving World creation and Runtime resumability preserve Loom API, Runtime authority, PostgreSQL persistence and Cargo dependency contracts.

## Revalidation checklist

- [x] public World creation yields fresh World + initial Timeline with explicit World Time and zero version;
- [x] identity allocation remains Runtime-owned/injectable and hidden from API;
- [x] lifecycle persistence remains Runtime-owned and PostgreSQL creation is atomic;
- [x] created Timeline immediately accepts normal semantic Actions;
- [x] Runtime reconstruction reads durable Event/State/Work and continues the same Timeline;
- [x] pending Work survives reconstruction with unchanged lease/fence/retry semantics;
- [x] existing M1/M2 validation/CAS/atomicity contracts remain green;
- [x] API/Runtime dependency boundaries remain compliant.

## Final gates

- [x] `python3 tools/check_architecture.py`;
- [x] `cargo fmt --all -- --check`;
- [x] `cargo check --workspace --all-targets --all-features`;
- [x] `cargo clippy --workspace --all-targets --all-features -- -D warnings`;
- [x] `cargo test --workspace --all-features`;
- [x] `RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps`;
- [x] PostgreSQL 18 scratch migrations/lifecycle/read/commit/Work suites (merged baseline CI);
- [x] restart/resume vertical suite (local PostgreSQL integration run; explicit CI step added in this candidate);
- [x] required GitHub Actions checks green on final candidate containing the new CI step (`32497391524`; PostgreSQL 18 restart/resume step passed).

## R-* linearization evidence

- Timeline/Event/State commits retain the existing PostgreSQL transaction and Timeline row lock at `crates/loom-storage/src/postgres/commit.rs:42-121,130-139`; the `TimelineVersion` CAS remains the sole business linearization point.
- Work claim/fence authority remains the existing row-locked transaction at `crates/loom-storage/src/postgres/work.rs:57-115,161-174`; current-Work status, lease and fence are rechecked in the same commit transaction at `crates/loom-storage/src/postgres/commit.rs:559-636`.
- The merged restart/resume scenario asserts the authority boundary after Runtime reconstruction at `crates/loom-storage/tests/postgres_restart_resume.rs:350-405`: prior Event/State/Work are read, the second Action advances the durable Facet, and inherited Work completes once with generation/attempt advancement and no lease.

## Completion evidence

- final candidate SHA: `68bf856c7429d63fe2aa621e826c5cea61ebd00b` (PR #57 head)
- PR: #57
- merge SHA: `060993b4935dcf92e99226cb50ee22303fda7ecb`
- CI runs: `32497391524` green for Rust Ubuntu, Rust macOS, and PostgreSQL 18 persistence contract, including the `PostgreSQL Runtime restart/resume vertical slice` step; merged baseline evidence remains `32495546544` / `32495589422`.
- archive: PR #58 merged as `eb833caeda4fff2fcd1b76e9030fbf5c56469b12`; required CI run `32498967338` is green for the docs-only archive candidate.
- notes: Final candidate `68bf856c7429d63fe2aa621e826c5cea61ebd00b` retains the previously accepted Runtime/Storage authority and R-* evidence. The archive candidate is PR #58 merge `eb833caeda4fff2fcd1b76e9030fbf5c56469b12` and changes only task-record completion metadata and evidence.

## Progress log

- 2026-08-21 — Task record created as the serial gate after #48/#49/#50.
- 2026-08-21 — Audited merged M3-T1/T2/T3 baseline `abbd8faa26f671f58bc69dff832469e92ebc3dbf`; architecture, format, workspace check, clippy, workspace tests and rustdoc all pass locally. M3-T1/T2/T3 PostgreSQL 18 evidence is carried by the merged CI history; the restart/resume test passed against the available local PostgreSQL 17 instance.
- 2026-08-21 — Added the required long-lived CI step `PostgreSQL Runtime restart/resume vertical slice`; final-candidate GitHub Actions and merge evidence remain pending because this Executor run cannot publish a PR.
- 2026-08-21 — PR #57 merged as `060993b4935dcf92e99226cb50ee22303fda7ecb`; required Actions run `32497391524` passed all jobs, including the PostgreSQL 18 restart/resume step. T4 archive evidence is complete.
- 2026-08-22 — PR #58 archive merged as `eb833caeda4fff2fcd1b76e9030fbf5c56469b12`; required CI run `32498967338` revalidated the archived task-record provenance.
