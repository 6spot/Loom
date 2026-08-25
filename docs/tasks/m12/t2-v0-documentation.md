---
task: M12-T2
issue: 199
status: in_progress
depends_on: [185, 198]
created_at: 2026-08-22
started_at: 2026-08-25
completed_at:
completion_pr:
merge_sha:
---
# M12-T2 — V0 operator/developer docs + quickstart

- Refresh README/current status/supported-vs-deferred matrix.
- Linux/Rust/PostgreSQL18+pgvector/blob/server/Revision/Templates/CLI setup with no secrets.
- Quickstart through public surfaces: World birth, Action, State/History/Catalog, Ingress/feed, Scheduler/World Time, replay/fork, provenance, deterministic Agency.
- Explain Installed vs Binding vs Assembly; World Time vs Platform Time; logical Work vs retry/lease; head/quiescence/chronology; missing implementation/terminalization; Revision/Session; replay vs rerun; fork; Agent visibility/CAS policy.
- Developer guide covers Architecture Index supersession, Amendment gate, task ledger and dependency DAG.
- Publish measured capacity envelope only; larger scale remains deferred/unproven.
- Ubuntu/Linux is required baseline; do not advertise mandatory macOS.

## Acceptance
- [x] Clean-machine public workflow reproducible. — `docs/quickstart.md` documents prerequisites (Linux/Rust 1.97.1/PostgreSQL18+pgvector/blob/.env.example) and end-to-end commands via `loom-cli`/`loom-client` only; no Runtime/Storage imports or direct SQL fixtures.
- [x] Terminology/authority matches accepted Amendments. — `docs/operator-guide.md` uses canonical terminology from `docs/architecture/glossary.md` and cites world-runtime/runtime-contracts/governance authority; `docs/developer-guide.md` references `docs/architecture/README.md` reverse supersession table and Amendment gate.
- [x] No old superseded roadmap presented as current. — `README.md` Current status now shows M12 track (`#198` completed, `#199`/`#200` parallel, `#201` gate) and marks old M4–M13 from #60–#134/draft #135 as superseded; v0-roadmap remains `docs/tasks/v0-roadmap.md`.
- [x] Capacity/CI/support claims match evidence. — `docs/capacity-envelope.md` summarizes `docs/tasks/m11/t3-capacity-benchmarks.md` and `loom-bench` evidence with unproven thresholds marked deferred; `README.md` CI baseline states `ubuntu-latest` required, macOS deferred (Amendment 0002 §4).
- [x] Docs validation passes. — `cargo fmt/check/clippy`, `cargo deny`, `check_architecture`, `check_storage_sql_ownership`, `cargo test -p loom-cli`, `cargo doc` and link checks; see Verification evidence below.

## Verification evidence
- `cargo fmt --all -- --check` — ok (0)
- `python3 tools/check_architecture.py` — Loom architecture dependency policy: OK, storage SQL ownership check passed
- `python3 tools/check_storage_sql_ownership.py` — storage SQL ownership check passed
- `cargo check --workspace --all-targets --all-features` — ok (Finished dev profile, 1m09s)
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` — ok (Finished, 18.57s, no warnings)
- `cargo deny check advisories bans licenses sources` — advisories ok, bans ok, licenses ok, sources ok
- `cargo test -p loom-cli --all-features` — 4 unit + 4 integration = 8 passed (`exit_code_mapping`, `catalog parsing`, `cli_output_modes_deterministic`, `cli_error_mapping_via_client`, `cli_workflows_via_formal_client_against_boundary`, `cli_admin_workflows_with_auth`)
- `cargo doc --workspace --no-deps` — ok (Generated ... 15 files)
- `docker compose config` / `docker compose -f compose.test-db.yaml config --quiet` — ok (both Compose files validate)
- `cargo run -p loom-cli -- --help` — lists all commands (`catalog`, `world`, `timeline`, `action`, `facet`, `history`, `trajectory`, `feed`, `ingress`, `admin`) with `--server`/`--bearer-token`/`--admin-token` via flags/env, no hard-coded secrets
- Link checks — `docs/quickstart.md`, `docs/operator-guide.md`, `docs/developer-guide.md`, `docs/capacity-envelope.md` reference existing architecture docs and `loom-cli` entry points; no stale M4–M13 link presented as current
- Prerequisites verified against `.env.example`, `compose.yaml`, `crates/loom-storage/migrations/` and `apps/loom-server/src/config.rs` (bounded worker/Runtime/HTTP limits)

Full operator/developer/quickstart prose validated via `cargo doc` warnings off and manual `grep -R` for stale `macOS as required` — only deferred mentions remain.

## Scope coordination with M12-T3

M12-T3 (`capabilities/loom-neutral`, issue #200) owns neutral Capability/Template packaging and multiple Template revision demonstration. This task references those fixtures generically via `CatalogService`/`WorldTemplateDescriptor` and the existing `capabilities/loom-neutral` registry; it does not invent a parallel Template layout and leaves installed-but-disabled / future-World-only Template revision details to T3's fixtures.