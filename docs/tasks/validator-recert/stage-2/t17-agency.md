---
task: VALR-T17
issue: 322
status: blocked
depends_on: [314]
architecture_blocker: true
created_at: 2026-08-26
started_at: 2026-08-27
completed_at:
completion_pr:
merge_sha:
---

# VALR-T17 — Validate Agency Wake NoAction/Act/rejection/CAS behavior

Blocking ledger leaf. The current `loom-api` / `loom-client` / `BackendHarness` boundary provides no public/controlled seam to deterministically drive an Agency Wake through `NoAction` / `Act` / semantic `Rejected` to a terminal `TimelineVersion` CAS, nor to create or observe a concurrent `claim` / fence CAS loser. `CV-034..CV-037` remain `blocked` per frozen matrix `t08-coverage-matrix.md`. This ledger records the per-CV blocked reason, the missing future public seam, and the evidence that cannot be claimed. No Validator scenario, CV registration, `loom-api`/`loom-runtime`/`loom-storage`/`loom-boundary` change, central registry edit, or CAS winner/resample/reuse/fence policy invention is part of this leaf.

Race protocol: closed — this leaf only records the blocking ledger; it performs no `claim`/`release`/`terminal`/`idempotency`/`retry` or concurrency strategy.

## Goal

Confirm, on the current checkout, whether `CV-034..CV-037` can be validated as a public/controlled consumer through formal surfaces. If the gap closed, the next leaf would implement the dedicated Agency suite; because the gap still holds, this leaf stops after the blocked ledger so later Executors do not invent agency execution or CAS policy in Validator code.

## Gap Confirmation on Current Main `da18e40`

Verification performed on `da18e40d30697f57f38a3f21a14de666ebfefc54` (`origin/main` post `VALR-T09` scaffold):

```bash
grep -rn "schedule_agency_wake" crates/loom-api/src --include="*.rs"
# -> crates/loom-api/src/admin.rs:678 fn schedule_agency_wake(...)
#    crates/loom-runtime/src/orchestration.rs:1274 pub async fn schedule_agency_wake
#    (only scheduling, no execution)

grep -rn "execute_work" crates/loom-api/src --include="*.rs"
# -> 0 results (no public AdminService::execute_work)

grep -rn "with_cognitive_executor\|CognitiveExecutor\|Decision" crates/loom-api/src --include="*.rs"
# -> 0 results (CognitiveExecutor/Decision live only in crates/loom-runtime/src/cognitive.rs, crates/loom-runtime/src/orchestration.rs)

grep -rn "with_cognitive_executor\|execute_work\|CognitiveExecutor" apps/loom-validator --include="*.rs"
# -> 0 results (no controlled harness seam; tests/common/mod.rs composes Runtime without exposing with_cognitive_executor)

grep -rn "claim" crates/loom-api/src --include="*.rs" | grep -i work
# -> 0 results (no public claim_work / fence token API; only AdminService::terminalize_work + timeline_logical_status reads)
```

Conclusions:

- `AdminService` (`crates/loom-api/src/admin.rs:568-700`) exposes `schedule_agency_wake(AdminScheduleAgencyWakeRequest { target, expected_version, work_id, agent, cognition, payload, schedule }) -> AdminScheduleAgencyWakeResult` (scheduling only) and `timeline_logical_status` / `terminalize_work` reads; it does not expose `execute_work`, `claim_work`, `with_cognitive_executor`, or a fence token injection surface.
- `AdminScheduleAgencyWakeRequest.cognition: String` is a stable cognition-implementation requirement, not a `Decision` provider. `Runtime::with_cognitive_executor(DeterministicCognitiveExecutor)` (`crates/loom-runtime/src/orchestration.rs:253`) and `Runtime::execute_work(target, work_id, now, claimed_until, retry_available_at)` (`orchestration.rs:1339`) are `loom-runtime` application-composition APIs, not `loom-api` / `loom-client` public surfaces and not exposed via `BackendHarness` / `tests/common`.
- No public/controlled `Decision` injection (`Decision::NoAction` / `Decision::Act(ActionInvocation)`) + `execute_work` seam exists that a Validator scenario could drive through `LoomClient` or a controlled harness without bypassing normal Action authority or importing `loom-runtime` directly into production validator code.
- No public `claim` / `execute` / `fence` CAS surface exists to create or observe concurrent winner/loser, resample/reuse policy, or provenance `discarded`/`reused` dispositions via formal API.

Gap still holds, identical to `t08-coverage-matrix.md` CV-034..037 `blocked` entries and Coverage Gaps 15/16/17. This leaf therefore does not implement Validator behavior and does not select a policy.

## Per-CV Blocked Ledger

### CV-034 — Agency NoAction completes wake without fabricating Event (`m10/t4`, `amendment 0003 §3.5`)

- **Blocked reason:** No public/controlled `with_cognitive_executor(DeterministicCognitiveExecutor)` + `execute_work` seam exists to deterministically inject `Decision::NoAction` and drive the Wake `Pending -> Completed` without a committed Event. `AdminService::schedule_agency_wake` only creates `Pending` Work (`work_id`, `agent`, `cognition: String`, `payload`, `schedule`); the `NoAction` terminal transition cannot be invoked via `loom-api` / `loom-client` / `BackendHarness`.
- **Missing future public seam:** A public, controlled Agency execution seam that (a) allows a Validator-controlled harness to inject a deterministic `CognitiveExecutor` producing `Decision::NoAction` and (b) exposes `execute_work` (or an equivalent formal Work execution operation) through `loom-api` / `loom-client` without requiring production validator to import `loom-runtime` or bypass normal authority. The seam must preserve normal validation/commit rules and remain distinct from `cognition: String` requirement passthrough.
- **Irrepresentable / cannot claim:** `Pending -> Completed` with no `CommittedEvent` for the Wake; `HistoryService::list_events` count unchanged proof; `AdminService::timeline_logical_status` removal / `Completed` transition for `work_id`; `AdminService::get_execution_session` / `AdminCognitiveEvidence` `outcome == NoAction` with `disposition == Fresh`; PostgreSQL durability variant. Current observable via `schedule_agency_wake` alone is only `Pending` Work visible in `timeline_logical_status`; none of the `NoAction` terminal evidence can be produced or observed via public surface.
- **Provenance:** `cognitive_evidence.observations[0].outcome == NoAction`, `disposition == Fresh` would be retained in Session provenance only if execution were drivable — not claimable today.

### CV-035 — Agency Act enters normal Action authority path (`m10/t4`)

- **Blocked reason:** Same seam absence as CV-034. No `Decision::Act(ActionInvocation::new("neutral.counter.increment", ...))` injection seam exists to drive `Act` through the normal Action authority/validation/commit path. `cognition: String` is not a `Decision`; `schedule_agency_wake` only creates `Pending`.
- **Missing future public seam:** Same controlled cognitive-injection + Work-execution seam as CV-034, with the additional requirement that the `Act` path commits through normal Action resolution (`ActionService::invoke` authority, schema validation, commit rules) and exposes the committed Event via `HistoryService` / `QueryService` as if the Action had been invoked directly. No direct `loom-runtime` inspection bypass is allowed.
- **Cannot claim:** Successful `Act` visible through normal World history/state (`HistoryService::list_events` contains committed `EventId` from the Wake's `Act`, `QueryService::get_facet` reflects committed state, `TimelineVersion` increments via same authority as direct `ActionService::invoke`); `AdminCognitiveEvidence` `outcome == Act` + `disposition == Fresh`; Session `event_refs` not empty; no authority bypass used. None producible via `schedule_agency_wake` alone.
- **Note:** Must not bypass normal Action authority to make the test simpler; no such bypass is added here.

### CV-036 — Agency semantic rejection produces no false Event (`m10/t4` R-1, `runtime-contracts.md` §5.4)

- **Blocked reason:** No public/controlled cognitive-injection + `execute_work` seam to drive a `Decision::Act` that semantically fails validation and yields `ExecutionResult::Rejected` / `IngressCompletion::Rejected` equivalent without producing a false committed Event. `schedule_agency_wake` only creates `Pending`; `ExecutionResult::Rejected` cannot be observed via that call alone.
- **Missing future public seam:** Same controlled seam as CV-034/035, extended to surface `Rejected` as the expected terminal outcome (`ExecutionResult::Rejected` with `Rejection` details) rather than mapping to `Retryable`/`Failed` or to a fabricated Event. Requires formal observation path for `Rejected` via public API (e.g., via Work terminalization / `ExecutionSession` status / `IngresStatus` analogue for Agency, as defined by a future Architecture Amendment).
- **Cannot claim:** `Rejected` result exposed with correct `Rejection` code, no fabricated authoritative Event in `HistoryService::list_events` (`list_events` count unchanged, `get_facet` reflects no mutation, `TimelineVersion` reflects `NoChange` / `Rejected` terminalization as per `m10/t4` R-1); `AdminCognitiveEvidence` `outcome == Act` that maps to `Rejected` disposition; negative case with no false `EventRef`. Only `Pending` is observable today.
- **Complementary internal evidence (does not replace Validator):** `m10/t4` R-1 rejected wake completes, `loom-runtime` rejected path — internal, not public Validator evidence.

### CV-037 — Concurrent/stale CAS loser cannot overwrite winner; provenance records path (`m10/t5`, `world-runtime.md` §8.1)

- **Blocked reason:** No public `claim_work` / `execute_work` / `fence` token injection surface exists to create or observe a concurrent `CAS` winner/loser. `AdminService::schedule_agency_wake` is scheduling only; `timeline_logical_status` is read-only; `Runtime::execute_work` claim is internal scheduler (`loom-runtime`) not exposed via `loom-api` / `loom-client` or controlled harness. Concurrent `CAS` with `expected_version` fencing cannot be driven.
- **Missing future public seam:** A public, controlled scheduler `claim` / `execute` / fence-injection API that (a) allows two workers to `claim` the same logical head `work_id` with distinct `TimelineVersion`/`fence` generations (`expected_version` CAS), (b) lets the Validator observe that the stale/losing `CAS` cannot overwrite the winner's committed state (`TimelineVersion` CAS linearizes, `EventSeq` of winner preserved), and (c) exposes provenance of the actual path taken (`AdminCognitiveEvidence` `disposition == Discarded` / `Reused`, `fresh_count`/`reused_count`/`discarded_count`, `DecisionReusePolicy` choice) without the Validator inventing the policy. The seam must not require importing `loom-storage` or fabricating a second authority.
- **Cannot claim:** Controlled competing/stale `CAS` case proving loser cannot commit stale authority (History `list_events` shows exactly one winner Event, not two); provenance observation for selected/resampled/reused path where exposed by formal contract (`AdminCognitiveEvidence` `observations` with `disposition` `Discarded`/`Reused` and `decision_reuse: Resample` vs `ReuseDeterministic`); `timeline_logical_status` shows winner consumed, loser discarded; PostgreSQL live concurrency variant. None of this can be produced or observed via current `schedule_agency_wake` + `timeline_logical_status` read-only surface. Must not choose or invent `CAS` winner / resample / reuse / fence policy in Validator code — this ledger explicitly defers the choice to a future Architecture Amendment.
- **Stop condition preserved:** If the architecture does not specify the required `CAS` resample vs reuse behavior, the Validator stops and escalates instead of selecting a policy. This ledger escalates.

## Missing Seams Summary (future public surface, not invented here)

All four CVs share the same root gap. A future Architecture Amendment adding a public Agency execution surface must define, at minimum, without inventing policy in Validator code:

1. **Deterministic `CognitiveExecutor` injection for Validator harnesses** — a `loom-api` / `loom-client` / `BackendHarness`-exposed way for controlled tests to supply a deterministic `Decision` provider (`DeterministicCognitiveExecutor` or equivalent) distinct from the non-secret `cognition: String` requirement field. Must not be application-only `Runtime::with_cognitive_executor` composition.
2. **Work execution driver** — a public `execute_work` / `claim` / `drive` operation through `LoomClient` / `AdminService` that exercises the same `Runtime::drive_timeline` / `execute_work_inner` authority as production, with the same `TimelineVersion` CAS, validation, and provenance retention. Must not bypass normal authority to simplify tests.
3. **Observation surfaces** — formal reads for `ExecutionResult::Committed` / `NoChange` / `Rejected`, `AdminTimelineLogicalStatus` `works` transition to `Completed`, `HistoryService` / `QueryService` authority truth, and `AdminExecutionSession` / `AdminCognitiveEvidence` / `AdminEventSessionLookup` Session-to-Revision provenance for `NoAction` / `Act` / `Rejected`.
4. **Concurrent CAS / fence seam** — a public claim/fence injection surface with `expected_version` CAS and `fence` generation so competing workers can race on the same `work_id` and the Validator can observe winner linearizes, loser is fenced, and provenance records `Discarded` / `Reused` per `DecisionReusePolicy` (`Resample` vs `ReuseDeterministic`). The policy value itself must be architecture-specified, not Validator-invented.
5. **Durability / controlled restart** — seam must be usable in `InMemory` and controlled `PostgreSQL` harnesses with `BackendContext::restart()` + `RestartCapability::ControlledBoundaryRestart` so future Validator evidence can be classed `controlled InMemory` / `controlled PostgreSQL` rather than `blocked`.

Until such Amendment lands, `CV-034..037` must remain `blocked (no public/controlled Agency execution surface)` / `blocked (no public/controlled claim surface)` with `PostgreSQL live: No — blocked`, as already frozen in `t08-coverage-matrix.md`.

## Evidence That Cannot Be Claimed Until Seams Exist

- Deterministic `NoAction` terminal completion with no fabricated `Event` (`CV-034`).
- `Act` committed via normal Action authority path visible in `HistoryService` / `QueryService` (`CV-035`).
- Semantic `Rejected` with no false `Event` and expected `Rejection` result (`CV-036`).
- Controlled competing / stale `CAS` loser cannot overwrite winner; provenance records `Discarded` / `Reused` / `Resample` per-documented policy (`CV-037`).
- Any `controlled InMemory` / `controlled PostgreSQL` / `External` or `controlled restart` evidence class for these four CVs — all remain `blocked`.
- PostgreSQL live durability / concurrency evidence for `CV-034..037`.

Citing internal `loom-runtime` / `loom-agency` / `loom-storage` tests (`m10/t4`, `m10/t5`, `DeterministicCognitiveExecutor` unit tests, `postgres_work_stale_completion`, `agency_wake_resample` / `agency_wake_reuse`) as public Validator `Pass` is explicitly not allowed; they remain complementary internal evidence only.

## What This Ledger Does Not Do (Forbidden Scope Compliance)

- Does not implement `CV-034..CV-037` Validator scenarios, suite modules (`apps/loom-validator/src/agency.rs` remains scaffold-only with `owns_cv` boolean, no `ScenarioDescriptor`), or integration tests (`apps/loom-validator/tests/agency.rs` remains non-registering scaffold).
- Does not register any `CV-012..CV-040` ID in `validator_registry` / `registry.rs` / `scenarios.rs` / `--list` (still `CV-001..CV-011` only); no `ScenarioId::new("CV-03")` added.
- Does not edit `loom-api`, `loom-runtime`, `loom-storage`, `loom-boundary`, central registry, or wire internal `Runtime` into production validator.
- Does not choose or invent `CAS` winner, `resample` vs `reuse` vs `fence` policy; the previous `DecisionReusePolicy::Resample` / `ReuseDeterministic` definitions in `loom-api` / `loom-runtime` are referenced only as existing internal policy vocabulary, not as a Validator-selected winner. The winner/resample/reuse/fence choice remains an explicit architecture gap to be decided via Amendment, not Validator code.
- Does not add a second authority, shared helper, or public API surface.

## Verification Evidence (this leaf)

Gap re-confirmed before writing this ledger:

- `grep -rn "schedule_agency_wake" crates/loom-api/src` — only `AdminService::schedule_agency_wake` (scheduling).
- `grep -rn "execute_work" crates/loom-api/src` — 0 results.
- `grep -rn "with_cognitive_executor\|CognitiveExecutor" crates/loom-api/src` — 0 results.
- `grep -rn "with_cognitive_executor\|execute_work\|CognitiveExecutor" apps/loom-validator` — 0 results (no harness seam).
- `grep -rn "CV-0" apps/loom-validator/src --include="*.rs" | grep -v "#\[cfg(test)\]" | grep -v "SUITE\|CV_RANGE\|owns_cv"` — only `CV-001..CV-011` in `lifecycle` / `scenarios` / `runtime_authority`; no `CV-034..CV-037` registration.
- `cargo run -q -p loom-validator -- --list` — 11 scenarios (`CV-001..CV-011`) unchanged.
- `cargo check -p loom-validator --all-targets` — clean (scaffold plus this ledger only, no production code change).
- `cargo fmt --all -- --check` — clean.
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json` — `valid=true`, `record_count=10`, `ready=[VALR-T09]`, `blocked=[VALR-T17]` with `reasons: explicit architecture-decision blocker is recorded` + `dependency 314 is in_progress, not completed` (expected; T09 scaffold not yet marked `completed`). No violation.
- `python3 tools/check_architecture.py` — `Loom architecture dependency policy: OK`.
- `python3 tools/check_storage_sql_ownership.py` — `storage SQL ownership check passed`.
- `git diff --check` — no whitespace errors.

## Acceptance

- [x] `CV-034` blocked reason, missing future public seam, and non-claimable evidence are explicitly recorded above (no public/controlled cognitive-injection + `execute_work` seam; `schedule_agency_wake` only creates `Pending`).
- [x] `CV-035` blocked reason, missing seam, and non-claimable evidence are explicitly recorded (no `Decision` injection; no `Act` via normal authority without seam).
- [x] `CV-036` blocked reason, missing seam, and non-claimable evidence are explicitly recorded (no `Rejected` observation via `schedule_agency_wake` alone).
- [x] `CV-037` blocked reason, missing seam, and non-claimable evidence are explicitly recorded (no public `claim`/`execute`/`fence` CAS surface; winner/loser provenance cannot be observed; must not invent `CAS` winner/resample/reuse/fence policy).
- [x] No Validator scenario was implemented, no CV-034..037 was registered, no `loom-api`/`loom-runtime`/`loom-storage`/`loom-boundary`/central registry was edited, no internal `Runtime` was wired into production validator, and no `CAS` winner/resample/reuse/fence policy was chosen or invented.
- [x] `apps/loom-validator/src/agency.rs` and `tests/agency.rs` remain scaffold-only, `validator_registry` remains 11 scenarios, `cargo fmt/check/clippy/test` and `validator_ready` / `check_architecture` remain green (or expected `blocked` without violation).

## Progress Log

- 2026-08-27 — Confirmed public/controlled API gap on `da18e40` (no `execute_work` / `with_cognitive_executor` / `claim` surface in `loom-api` / `loom-client` / `BackendHarness`; `schedule_agency_wake` only creates `Pending`). Created this blocking ledger `docs/tasks/validator-recert/stage-2/t17-agency.md` with per-CV (`CV-034..CV-037`) blocked reason, missing future public seam, and non-claimable evidence; explicitly deferred `CAS` winner/resample/reuse/fence policy to a future Architecture Amendment. No Validator scenario, CV registration, or `loom-*` public API change was made.
