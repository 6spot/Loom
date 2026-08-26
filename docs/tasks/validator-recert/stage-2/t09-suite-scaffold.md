---
task: VALR-T09
issue: 314
status: in_progress
depends_on: [313]
created_at: 2026-08-26
started_at: 2026-08-27
completed_at:
completion_pr:
merge_sha:
---

# VALR-T09 — Create parallel-safe Validator suite scaffold

Scaffold-only leaf. Create deterministic per-suite module/test boundaries so T10–T18 can be implemented in parallel without editing the central registry or each other's files. No `CV-012..CV-040` behavior, no `Pass` placeholder, and no central registry integration are part of this leaf. No production semantics beyond module declarations are implemented.

## Goal

Provide a compile-clean, parallel-safe scaffold that:

- reserves one disjoint production module and one integration-test module per capability suite, aligned with the T08 frozen matrix `t08-coverage-matrix.md` “Parallel-Safe Implementation Boundary (for T09)”;
- exposes suite boundaries so each later leaf (T10–T18) can compile and test its own module without editing the central registry or dispatch;
- keeps placeholders non-executable and incapable of producing `Pass` findings;
- documents exact ownership/write scopes for T10–T18 and the T19 central-registry boundary so later Executors cannot race on the same file;
- preserves `CV-001..CV-011` registration unchanged at `--all`.

## Scope

Allowed:

- Creating the nine production suite modules and nine matching integration-test modules listed below;
- Declaring `pub mod <suite>` in `apps/loom-validator/src/lib.rs` to expose boundaries;
- Adding this ledger record `t09-suite-scaffold.md`.

Forbidden (per Leader standard):

- Do not implement `CV-012..CV-040` behavior; do not add placeholder `Pass` results;
- Do not register any new scenario in `validator_registry`, `registry.rs`, `scenarios.rs`, or `--all` — T19 owns central registry integration;
- Do not change `loom-core` / `loom-runtime` / `loom-storage` / `loom-boundary` / `loom-api` / `loom-client` public API or semantics;
- Do not edit the central CLI dispatch or group registration;
- Do not add a shared helper contract unless demonstrably common to multiple suites (proven common fixture wrapper — none extracted in this leaf because no such commonality is proven beyond existing `tests/common`);
- Do not modify unrelated Validator modules;
- Do not touch T08 or T01–T07 ledger records.

## Produced Scaffold

Nine production suite modules (disjoint, one per leaf):

| Suite module | Owner leaf | GitHub | CV range | Count |
| --- | --- | --- | --- | --- |
| `apps/loom-validator/src/world_binding.rs` | T10 World/Binding/Runtime Revision | #315 | `CV-012..CV-014` | 3 |
| `apps/loom-validator/src/action_ingress.rs` | T11 Action + durable Ingress | #316 | `CV-015..CV-017` | 3 |
| `apps/loom-validator/src/scheduler.rs` | T12 Scheduler + fencing | #317 | `CV-018..CV-020` | 3 |
| `apps/loom-validator/src/world_time.rs` | T13 World Time/Chronology/Reaction | #318 | `CV-021..CV-024` | 4 |
| `apps/loom-validator/src/query_catalog.rs` | T14 Query/History/Catalog | #319 | `CV-025..CV-027` | 3 |
| `apps/loom-validator/src/semantic_blob.rs` | T15 Semantic/Blob/Pinned Reads | #320 | `CV-028..CV-030` | 3 |
| `apps/loom-validator/src/provenance.rs` | T16 Session/Revision/Provenance | #321 | `CV-031..CV-033` | 3 |
| `apps/loom-validator/src/agency.rs` | T17 Agency Wake | #322 | `CV-034..CV-037` | 4 |
| `apps/loom-validator/src/change_feed.rs` | T18 Change Feed/SSE/formal client | #323 | `CV-038..CV-040` | 3 |

Nine matching integration-test modules:

- `apps/loom-validator/tests/world_binding.rs`
- `apps/loom-validator/tests/action_ingress.rs`
- `apps/loom-validator/tests/scheduler.rs`
- `apps/loom-validator/tests/world_time.rs`
- `apps/loom-validator/tests/query_catalog.rs`
- `apps/loom-validator/tests/semantic_blob.rs`
- `apps/loom-validator/tests/provenance.rs`
- `apps/loom-validator/tests/agency.rs`
- `apps/loom-validator/tests/change_feed.rs`

Each production module exposes `SUITE`, `CV_RANGE`, `CAPABILITY_AREA`, `suite_name()`, and `owns_cv()` as a non-executable compilation entry point. No `ScenarioDescriptor`, no `validator_registry` call, no `ScenarioOutcome::Pass`. Each integration test asserts its suite's disjoint `owns_cv` boundary and that `validator_registry().len()==11` and `CV-012..CV-040` remain unregistered.

Module declaration is in `apps/loom-validator/src/lib.rs` as `pub mod <suite>;` only; no new registration code is added to `validator_registry()` in `lib.rs`, `registry.rs`, or `scenarios.rs`.

## Ownership / Write Scope Ledger

This ledger is the sole authority for file ownership through T19. Each leaf may write exactly one production file and one test file; all other shared locations are read-only until T19.

| Leaf | Primary production file (write-owner) | Primary test file (write-owner) | CV range | May also edit (with justification) | Must not edit |
| --- | --- | --- | --- | --- | --- |
| T10 (#315) | `src/world_binding.rs` | `tests/world_binding.rs` | `CV-012..CV-014` | Own production + test only; optional local helpers inside `src/world_binding.rs` | `src/lib.rs`, `src/registry.rs`, `src/scenarios.rs`, `src/cli.rs`, other `src/*.rs`, other `tests/*.rs`, `tests/common/mod.rs` unless proven shared harness needed (requires T09 amendment), `docs/tasks/validator-recert/stage-1/**`, `t08-coverage-matrix.md` |
| T11 (#316) | `src/action_ingress.rs` | `tests/action_ingress.rs` | `CV-015..CV-017` | Same | Same |
| T12 (#317) | `src/scheduler.rs` | `tests/scheduler.rs` | `CV-018..CV-020` | Same | Same |
| T13 (#318) | `src/world_time.rs` | `tests/world_time.rs` | `CV-021..CV-024` | Same | Same |
| T14 (#319) | `src/query_catalog.rs` | `tests/query_catalog.rs` | `CV-025..CV-027` | Same | Same |
| T15 (#320) | `src/semantic_blob.rs` | `tests/semantic_blob.rs` | `CV-028..CV-030` | Same | Same |
| T16 (#321) | `src/provenance.rs` | `tests/provenance.rs` | `CV-031..CV-033` | Same | Same |
| T17 (#322) | `src/agency.rs` | `tests/agency.rs` | `CV-034..CV-037` | Same | Same |
| T18 (#323) | `src/change_feed.rs` | `tests/change_feed.rs` | `CV-038..CV-040` | Same | Same |
| T19 (#324) | `src/registry.rs`, `src/lib.rs` (`validator_registry` + `pub mod` wiring + CLI dispatch), `t19-registry.md` | — | — (integrates `CV-012..CV-040`) | Only T19 may edit `src/registry.rs`/`src/lib.rs` central wiring and may read all suite modules to register their descriptors | Must not edit any `src/<suite>.rs` production logic; must not edit `tests/<suite>.rs` |
| T09 (#314) | `src/lib.rs` suite `pub mod` declarations (this leaf only) + this ledger `t09-suite-scaffold.md` + the nine `src/<suite>.rs` + nine `tests/<suite>.rs` scaffolds created here | — | — | Only this leaf creates all nine scaffolds and the central `pub mod` declarations | Must not implement behavior or register scenarios |

Rules:

- **Disjoint primary ownership:** No two leaves share a primary production or test file. The primary file is the only file that leaf may treat as authoritative for its CV range.
- **Central registry is frozen until T19:** T10–T18 must use local unit-test registries or fixture harnesses inside their own module/test file if they need a registry for isolated unit testing. They must not import or edit `apps/loom-validator/src/registry.rs` to register production scenarios, and must not call `validator_registry()` mutation paths to register `CV-012..CV-040`. Production `validator_registry()` is assembled only from `lifecycle`, `scenarios` (replay/fork), and `runtime_authority` until T19.
- **No placeholder Pass:** A `Finding` with `ScenarioOutcome::Pass` for `CV-012..CV-040` must not exist in `src/` or `tests/` until the owning leaf implements the real observation via the formal `loom-api`/`loom-client` surface. The scaffold's `owns_cv()` returns a boolean and does not construct evidence.
- **Shared helper contract:** Only a helper proven common to two or more suites may be extracted, and it remains owned by T09. In this leaf no such helper was extracted because no common fixture beyond existing `tests/common/mod.rs` (which composes `loom-runtime` + `loom-storage` + `neutral` + `loom-boundary` for `InMemory`/`PostgreSQL` harnesses) is proven. Suite-local helpers must stay inside the suite's own `src/<suite>.rs`.
- **Compilation without central edit:** After this scaffold, `cargo check -p loom-validator --all-targets` succeeds and each `cargo test -p loom-validator --test <suite>` compiles and runs solely against its own suite module + the stable 11-scenario registry. No later leaf needs to edit `lib.rs` or `registry.rs` to compile.
- **Stop condition:** If two suites genuinely require the same central semantic implementation (same `loom-api` surface or same storage semantics), stop and record the conflict in the T08 matrix Coverage Gaps rather than letting parallel leaves race on the same central file.

## Non-registration Rule

All `CV-012..CV-040` descriptors and executors are reserved but unregistered in this leaf. No new `ScenarioDescriptor::new("CV-012", ...)` .. `CV-040` appears in `apps/loom-validator/src/` outside `#[cfg(test)]` local harnesses, and no `register_*` call for `CV-012..040` is added to `validator_registry()`. Verification:

```bash
grep -rn "CV-0" apps/loom-validator/src --include="*.rs" | grep -v "#\[cfg(test)\]" | grep -v "SUITE\|CV_RANGE\|owns_cv"
# expected: only CV-001..CV-011 in lifecycle/scenarios/runtime_authority remain
cargo run -q -p loom-validator -- --list
# expected: exactly 11 scenarios CV-001..CV-011
```

Any test-only `CV-012` fixture ID (e.g., in `reports.rs` helpers) is not a registered scenario and does not appear in `validator_registry`.

## Verification Evidence

- `cargo fmt --all -- --check` → required by AC-04
- `cargo check -p loom-validator --all-targets` → required
- `cargo clippy -p loom-validator --all-targets -- -D warnings` → required
- `cargo test -p loom-validator --all-targets` → 9 new integration tests plus existing suite must pass; no ignored/filtered placeholder
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json` → `valid=true`
- `python3 tools/check_architecture.py` → `Loom architecture dependency policy: OK`
- `python3 tools/check_storage_sql_ownership.py` → `storage SQL ownership check passed`
- `git diff --check` → no whitespace errors

Pending Reviewer and CI post-merge verification.

## Acceptance

- [ ] All nine production modules and nine integration-test modules exist, compile, and have disjoint primary ownership matching the T08 matrix (AC-01).
- [ ] Global production registry and `--all` output remain at `CV-001..CV-011`; no unfinished `CV-012..CV-040` or placeholder `Pass` is registered (AC-02).
- [ ] Scaffold is usable as independent suite entry points without later T10–T18 editing central registry/dispatch; ownership/write-scope ledger is precise enough to prevent cross-suite races (AC-03).
- [ ] `cargo fmt` / `cargo check` / `cargo clippy -D warnings` / `cargo test --all-targets` / `validator_ready --check` / `check_architecture` / `check_storage_sql_ownership` / `git diff --check` are clean with no skipped result standing in for a required check (AC-04).

## Progress Log

- 2026-08-27 — Created nine production suite scaffolds (`world_binding`, `action_ingress`, `scheduler`, `world_time`, `query_catalog`, `semantic_blob`, `provenance`, `agency`, `change_feed`) plus nine matching `tests/<suite>.rs` integration scaffolds and exposed `pub mod` boundaries in `src/lib.rs` without touching `validator_registry`/`registry.rs`/`scenarios.rs`. No `CV-012..CV-040` behavior or `Pass` placeholder was added. Documented disjoint ownership/write scopes for T10–T18, T19 central-registry boundary, non-registration rule, and no-shared-helper decision.
