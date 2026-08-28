---
task: VALR-T17
issue: 322
status: in_progress
depends_on: [314]
architecture_blocker: false
created_at: 2026-08-26
started_at: 2026-08-27
completed_at:
completion_pr:
merge_sha:
---

# VALR-T17 — Validate Agency Wake NoAction/Act/rejection/CAS behavior

## Current remediation evidence

The former architecture blocker was narrowed to a test-only controlled Agency
harness, which is now present in
`apps/loom-validator/tests/agency.rs`; it composes the existing
`DeterministicCognitiveExecutor`, `Runtime::with_cognitive_executor`,
`Runtime::with_cognitive_policy`, `Runtime::execute_work`, and `InMemoryStore`
behind a real `loom-boundary` HTTP server. World/Work/Event/Facet/Timeline/
Session assertions read through `LoomClient`.

The current candidate is the exact baseline `95f7e7a0233cfa917d0c9656b990fd2af4996874`
plus the uncommitted test-only diff in this checkout.

| CV | Controlled evidence | Result |
| --- | --- | --- |
| CV-034 | `NoAction` completes the Wake as a Work-only commit; LoomClient reads Completed Work, unchanged History, absent Blob Facet, and Session cognitive `NoAction`/`Fresh` provenance. | pass (controlled InMemory) |
| CV-035 | `Act(neutral.blob.attach)` is returned by cognition and committed through normal Action authority; LoomClient reads the Event, Blob Facet, Event→Session linkage, and `Act`/`Fresh` provenance. | pass (controlled InMemory) |
| CV-036 | A test-only Capability returns typed semantic `Rejected`; Runtime completes the Wake without an Event or Facet mutation; LoomClient reads Rejected Work Session and unchanged History. | pass (controlled InMemory) |
| CV-037 | Two independent Runtime worker paths claim the same Wake at different fences; the existing `InMemoryStore::inject_scheduler_conflict_once_for_test` performs real authority terminalization before Scheduler CAS. LoomClient reads one surviving Event/Facet, Completed/Cancelled Work, and discarded→fresh (`Resample`) or discarded→reused (`ReuseDeterministic`) Session provenance; the stale worker returns an error without overwriting the winner. | pass (controlled InMemory) |

No new public Decision/execute/fence API, central registry entry, production
Runtime/Storage change, T08 change, or T22 change was made. The Agency
execution remains test-only and controlled; no PG18 result is claimed here.

The following is the preserved historical blocked-boundary audit from before
the controlled test harness was added; its blocked conclusions are superseded
by the remediation evidence above.

Race protocol: enabled and executed in this leaf. Two Runtime workers target
the same Wake with distinct claims/fences; the existing storage seam is the
only injected scheduler conflict and uses real authority terminalization.
Timeline logical version and Work status are read through LoomClient, and the
stale worker cannot write the winning World/Work state.

## Historical authority and current-main boundary audit (superseded)

The governing sources are T08's frozen rows and detailed specifications,
Amendment 0003 §§3.2–3.7, completed M10-T4/M10-T5, and the current T22
certification manifest consumed by T25. M10 has fixed the semantics this ledger
must preserve:

- `Decision::NoAction` completes the current Agency Wake through a Runtime-owned
  Work-only logical commit with no World Event or state mutation.
- `Decision::Act(ActionInvocation)` re-enters normal Action owner, Binding,
  schema, resolution, validation, and commit authority; Wake completion and
  chronology consumption are part of the same commit attempt.
- **M10-T4 R-1:** semantic `Rejected` completes the current Wake as a
  determined no-world-change outcome. It must not remain Pending; later
  reconsideration is a new Wake.
- **M10-T5 v0 default:** CAS loss uses `Resample`. `ReuseDeterministic` is an
  explicit configured alternative only, with fresh-context and normal-authority
  revalidation. Both policy choice and discarded/reused cognition belong in
  Session provenance; Validator must not invent either policy.

The exact current boundary facts are:

| Surface | Current formal/public fact | CV consequence |
| --- | --- | --- |
| Agency scheduling | `AdminService::schedule_agency_wake` accepts Agent/cognition requirement/payload/schedule and commits a Pending Durable Work item (`crates/loom-api/src/admin.rs:503-536`, `:677-687`; `crates/loom-client/src/lib.rs:757-767`; boundary route `crates/loom-boundary/src/lib.rs:467-468`) | Scheduling is observable; it does not inject a `Decision` or execute the Wake. |
| Session/provenance reads | `AdminExecutionSession` publicly projects lifecycle, Event refs, read set, call provenance, entropy and `AdminCognitiveEvidence`; cognitive observations include executor/policy identity, Timeline version, outcome and `Fresh`/`Reused`/`Discarded` disposition (`crates/loom-api/src/admin.rs:129-223`, `:332-370`). Client and controlled boundary routes expose Session reads (`crates/loom-client/src/lib.rs:686-712`; `crates/loom-boundary/src/lib.rs:448-452`). | The observation contract exists, but no public Agency execution can create the required Agency Session through the Validator boundary. It is not correct to say the DTO is absent. |
| Timeline/Work reads and control | `AdminTimelineLogicalStatus` exposes version, chronology and Work summaries; `AdminService::terminalize_work` can operator-terminalize only `Dead` or `Cancelled` (`crates/loom-api/src/admin.rs:423-500`, `:665-675`) | These reads/control cannot produce Agency `NoAction`/`Rejected` execution results or a successful Wake terminal result. |
| Runtime internal composition | `Runtime::with_cognitive_executor` and `Runtime::execute_work` exist (`crates/loom-runtime/src/orchestration.rs:249-267`, `:1314-1355`); Agency dispatch claims internally at `:1421-1425` and enters the Agency branch at `:1412-1415` | These are `loom-runtime` application-composition/internal APIs, not `loom-api`/`loom-client` public Validator surfaces. Internal implementation/tests remain complementary only. |
| Controlled Validator boundary | The shared harness composes `Runtime::new` behind `router_with_admin` and returns an HTTP `LoomClient` (`apps/loom-validator/tests/common/mod.rs:318-342`); it has no cognitive executor injection or Work execution driver | Production Validator scenarios cannot import Runtime/Storage or bypass Action authority to manufacture the missing evidence. |

Therefore the gap is narrower and more precise than the historical ledger: the
formal Session cognitive-provenance *read model* is present, while the formal
Agency execution *drive/injection* and claim/fence *control* seams are not.

## Per-CV blocked ledger and T22/T25 alignment

### CV-034 — NoAction completes the Wake without fabricating an Event

- **Public/formal blocker:** No `loom-api`/`loom-client`/controlled-boundary
  operation injects a deterministic `Decision::NoAction` and invokes the
  Runtime Agency Work path. `schedule_agency_wake` stops after creating Pending
  Work; `terminalize_work` is only the separate Dead/Cancelled operator control.
- **Current observable:** The scheduled Work can be read as Pending through
  `timeline_logical_status`; Session reads and cognitive evidence types exist,
  but no Agency execution Session/result can be produced via this boundary.
- **Evidence not claimable:** Pending→Completed with no Event, unchanged
  `HistoryService::list_events`, completed Work/chronology transition, or a
  Session observation of `NoAction` + `Fresh` (including controlled PG18
  durability/restart).
- **T22/T25 manifest:** T22 `t22-certification-manifest.md:103` keeps this row
  `gap` with no executable `CV-034` test and no public/controlled execution
  seam. T25 must consume that gap, not treat internal M10 evidence as ready.

### CV-035 — Act enters the normal Action authority path

- **Public/formal blocker:** `AdminScheduleAgencyWakeRequest.cognition` is a
  stable String requirement, not a `Decision` provider. There is no public
  deterministic Decision injection plus Agency `execute_work` operation that
  can cause `Decision::Act(ActionInvocation)` to re-enter normal Action
  authority.
- **Current observable:** Scheduling, ordinary direct `ActionService::invoke`,
  history/facet reads, and generic Session projections exist independently;
  none proves that an Agency Act used the normal Action route.
- **Evidence not claimable:** Wake-produced committed Event/Facet/Timeline
  version, `Act` + `Fresh` cognitive provenance, Session event linkage, or
  proof that no authority bypass was used. No Validator scenario or registry
  entry is added.
- **T22/T25 manifest:** T22 `t22-certification-manifest.md:104` keeps this row
  `gap`; its named agency test is the non-registering scaffold only. The row's
  required Act evidence remains unavailable to T25.

### CV-036 — Semantic Rejected produces no false Event

- **Public/formal blocker:** There is no public controlled injection/execute
  operation that can drive an Agency `Decision::Act` through semantic
  validation and expose the resulting `ExecutionResult::Rejected`/terminal
  outcome. `schedule_agency_wake` alone cannot observe rejection.
- **Current observable:** The public API has generic Session status vocabulary
  including `Rejected` and `NoChange`, plus Timeline/History/Query reads, but
  no Agency execution path that can populate those observations.
- **Evidence not claimable:** Correct R-1 completion of the current Wake,
  unchanged Event count/facets, expected rejection details, no false EventRef,
  and controlled PostgreSQL evidence. M10-T4 R-1 is a fixed semantic contract,
  not an unmade policy decision.
- **T22/T25 manifest:** T22 `t22-certification-manifest.md:105` keeps this row
  `gap` because public `Rejected` observation is not reachable from the
  current Agency scheduling surface. Internal R-1 tests do not upgrade it.

### CV-037 — Concurrent/stale CAS loser cannot overwrite the winner

- **Public/formal blocker:** No public controlled `claim`/`execute`/fence
  operation lets Validator create two workers for one Agency Wake, supply or
  observe Work claim generation/lease and expected `TimelineVersion`, or
  observe the losing result. `Runtime::execute_work` performs claim internally;
  `AdminTimelineLogicalStatus` is read-only for this purpose.
- **Required authority when a seam exists:** Timeline logical Work and World
  History/Session provenance are authoritative; the single linearization point
  is Runtime-owned TimelineVersion CAS logical commit; the controlled clock is
  fixed WorldInstant/PlatformTime; the winner holds the current Work fence and
  passes expected-version CAS; one Wake has at most one deterministic terminal
  completion; a stale/CAS loser writes neither World nor Work. The result follows
  the already-defined v0 default `Resample`, or explicitly configured
  `ReuseDeterministic` with fresh-context revalidation, with provenance recorded.
- **Evidence not claimable:** A competing/stale Worker case with exactly one
  winning Event/commit, loser fencing, terminal Work state, and cognitive
  `Discarded`/`Reused`/policy provenance; no Validator or PG18 concurrency claim
  can be made. This leaf does not select a policy or execute the race.
- **T22/T25 manifest:** T22 `t22-certification-manifest.md:106` keeps this row
  `gap` for the missing public claim/execute/fence surface. T25 must retain the
  gap until that formal seam is supplied and independently exercised.

## Complementary internal and PG18 evidence boundary

M10-T4/M10-T5 and internal Runtime/Storage tests establish the implementation
contract, including R-1, Timeline CAS, fencing, and the explicit
`Resample`/`ReuseDeterministic` provenance vocabulary. They are useful
complementary evidence only. They do not become Validator evidence because
they use `loom-runtime`/`loom-storage` internals or application composition
instead of the formal `loom-client` boundary. In particular, internal Agency
tests, `postgres_work_stale_completion`, and Agency resample/reuse tests cannot
claim CV-034..CV-037's required public consumer, controlled restart, or PG18
live concurrency evidence.

T22's current summary (`t22-certification-manifest.md:129-153`) lists
`CV-034..CV-037` among the nine capability gaps and states that final V0
certification remains blocked. No separate T25 final-certificate ledger is
present on this current main checkout; this T17 record therefore aligns to the
T22 manifest input and does not make a T25 certification claim.

## Scope guard and acceptance record

- [x] Rechecked the exact current-main candidate and recorded the precise
  public/formal boundary rather than reusing the historical `da18e40`/PR #348
  conclusion.
- [x] Recorded the existing Session cognitive-provenance observation surface
  and the still-missing Decision injection, Agency execution/terminal result,
  and claim/fence control seams.
- [x] Preserved the historical CV-034..CV-037 boundary audit and T22/T25
  alignment as superseded context after adding the authorized test-only
  harness evidence.
- [x] Preserved M10-T4 R-1 and M10-T5 v0 default `Resample`; did not describe
  these defined semantics as unresolved.
- [x] Did not modify central registry, T08/T09/other suites,
  `loom-api`/`loom-client`/`loom-runtime`/`loom-storage`/`loom-boundary`,
  production schema, or Validator scenario behavior; did not wire internal
  Runtime/Storage into a production Validator scenario.
- [x] Executable controlled CV-034..CV-037 evidence — **pass in the
  test-only InMemory harness**; no public production execution/fence API was
  added.
- [ ] PG18 live evidence — **not run**; this leaf uses the explicitly scoped
  controlled InMemory harness and makes no PostgreSQL claim.

## Verification evidence

All checks below were run on the exact candidate above:

- `git diff --check` — PASS (no whitespace errors).
- `cargo test -p loom-validator --test agency -- --test-threads=1` — PASS (5 tests: scaffold plus CV-034..CV-037; all required scenarios executed).
- `cargo fmt --all -- --check` — PASS.
- `cargo check -p loom-validator --all-targets` — PASS.
- `cargo clippy -p loom-validator --all-targets -- -D warnings` — PASS.
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json` — repository-wide result remains `valid=false` because of unrelated Stage-3/T19/T20/T21/T24 dependency violations; no T17 schema violation is claimed here.
- `python3 tools/check_architecture.py` — PASS (`Loom architecture dependency policy: OK`).
- `python3 tools/check_storage_sql_ownership.py` — PASS (`storage SQL ownership check passed`).
- `git diff --stat` and `git status --short --branch` — PASS for scope: only
  `Cargo.lock`, `apps/loom-validator/Cargo.toml`,
  `apps/loom-validator/tests/agency.rs`, and this T17 ledger are modified on
  branch `agent/executor/d8f55fafb258`.
- Targeted boundary audit — PASS for scope: production
  `loom-api`/`loom-client`/boundary surfaces remain unchanged; the test-only
  Validator harness composes Runtime/Storage as controlled drivers and reads
  all required evidence through LoomClient.

The controlled Agency target was executed serially. No PG18 live run was
requested or performed, so no PostgreSQL durability/concurrency result is
claimed.

## Progress log

- 2026-08-27 — Re-audited current `origin/main` at
  `6f22531a909d0becd1d7b30836168f76cd3d5d33`. Confirmed that Session cognitive
  provenance DTO/read routes and internal M10 Agency execution/policy code are
  present, while public Decision injection, Agency execution/result, and
  claim/fence control remain absent. Updated this ledger only; retained
  `CV-034..CV-037` as blocked and did not execute a race or choose a policy.
- 2026-08-28 — Reworked CV-037 after D-001: two Runtime worker paths now
  compete for the same Wake, use the existing real terminalization/CAS seam,
  and prove unique winner plus stale-worker fencing through LoomClient. The
  serial Agency target and required static checks pass; candidate remains
  baseline `95f7e7a0233cfa917d0c9656b990fd2af4996874` plus this test-only diff.
