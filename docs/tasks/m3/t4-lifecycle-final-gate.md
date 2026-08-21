---
task: M3-T4
issue: 51
status: planned
depends_on: [48, 49, 50]
created_at: 2026-08-21
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M3-T4 — World Lifecycle / Resumability Final Parity Gate

## Goal

Revalidate one final M3 candidate proving World creation and Runtime resumability preserve Loom API, Runtime authority, PostgreSQL persistence and Cargo dependency contracts.

## Revalidation checklist

- [ ] public World creation yields fresh World + initial Timeline with explicit World Time and zero version;
- [ ] identity allocation remains Runtime-owned/injectable and hidden from API;
- [ ] lifecycle persistence remains Runtime-owned and PostgreSQL creation is atomic;
- [ ] created Timeline immediately accepts normal semantic Actions;
- [ ] Runtime reconstruction reads durable Event/State/Work and continues the same Timeline;
- [ ] pending Work survives reconstruction with unchanged lease/fence/retry semantics;
- [ ] existing M1/M2 validation/CAS/atomicity contracts remain green;
- [ ] API/Runtime dependency boundaries remain compliant.

## Final gates

- [ ] `python3 tools/check_architecture.py`;
- [ ] `cargo fmt --all -- --check`;
- [ ] `cargo check --workspace --all-targets --all-features`;
- [ ] `cargo clippy --workspace --all-targets --all-features -- -D warnings`;
- [ ] `cargo test --workspace --all-features`;
- [ ] `RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps`;
- [ ] PostgreSQL 18 scratch migrations/lifecycle/read/commit/Work suites;
- [ ] restart/resume vertical suite;
- [ ] required GitHub Actions checks green on final candidate.

## Completion evidence

- final candidate SHA:
- PR:
- merge SHA:
- CI runs:
- notes:

## Progress log

- 2026-08-21 — Task record created as the serial gate after #48/#49/#50.
