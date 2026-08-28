---
task: VALR-T11
issue: 316
status: completed
depends_on: [314]
created_at: 2026-08-26
started_at: 2026-08-27
completed_at: 2026-08-28
completion_pr: 365
merge_sha: 95f7e7a0233cfa917d0c9656b990fd2af4996874
---

# VALR-T11 — Validate Action/Event/Facet + durable idempotent Ingress

Owner: T11 (#316) — `CV-015..CV-017`.
Primary files: `apps/loom-validator/src/action_ingress.rs`,
`apps/loom-validator/tests/action_ingress.rs`.
Consumed read-only: `apps/loom-validator/tests/common/mod.rs`.
Forbidden: central registry/dispatch, scheduler, core/runtime/storage/boundary/client
production changes, schema/migration/CI changes, and other suites.

## Goal and authority boundary

The suite validates the public `loom_api`/`loom_client` Action and Ingress
surfaces. `IngressAcceptance` and `IngressStatus` are operational bookkeeping;
authoritative World truth is observed only through public
`HistoryService::list_events` and `QueryService::get_facet`. A test may call
the existing `Runtime::process_ingress` only as a controlled worker/pump; it
must not use Runtime or persistence reads as acceptance evidence.

The race protocol is enabled only for the existing Ingress lifecycle boundary:
terminal public Ingress status is followed by public history/facet reads. No
new receipt, persistence, fence, retry policy, or `R-*` was added.

## Descriptors

`src/action_ingress.rs::descriptors()` exposes three local descriptors and does
not register them centrally:

- `CV-015` — accepted Action produces committed Event/Facet/history on
  InMemory, PostgreSQL, or a public client.
- `CV-016` — identical durable Ingress identity is accepted once and then
  deduplicated, with one authoritative mutation on controlled InMemory and
  PostgreSQL.
- `CV-017` — normal resolver failure reaches `Retryable`, leaves public World
  history/facet unchanged, and public Action recovery reaches one committed
  recovery Event. A service without a running worker reports `Unavailable`; no
  fault-injection API is invented.

## CV-015

`cv015()` creates a fresh deterministic World/Timeline through
`WorldService::create_world_from_template`, invokes `neutral.counter.seed`
through `ActionService::invoke`, and requires `ExecutionResult::Committed`.
It then reads the expected `neutral.counter.value` Facet and exactly one
matching Event through public `QueryService`/`HistoryService` calls, including
payload, EventId, ordered history, page, and advanced TimelineVersion.

## CV-016

`cv016()` submits a complete deterministic `IngressEnvelope` through public
`IngressService::submit_ingress`. Only a first `Accepted` receipt is a winner;
a first `Deduplicated` is an explicit non-Pass failure. The identical second
submission must be `Deduplicated` and reference the winner. Public
`ingress_status` is polled to `Completed(Committed)` with one EventRef, then
public history/facet reads prove one mutation. Controlled PostgreSQL performs a
real `PgServer` boundary restart and repeats status/history/facet reads with a
new public client.

## CV-017 remediation

The existing public surface can express the technical boundary without a new
fault-injection seam: a valid `neutral.counter.increment` Ingress against a
fresh World with no counter Facet causes the existing Runtime resolver failure
to be recorded as `Retryable(IngressTechnicalFailure)`. The controlled test
then reads `ingress_status`, `list_events`, and `get_facet` publicly to prove
that Retryable did not create World truth; it uses a public seed Action to make
the normal retry recover. The pump return value is ignored; the formal client
reads `Completed(Committed)` and its `event_refs`, requiring exactly one
recovery EventRef, ordered history, and the final Facet publicly.

`tests/action_ingress.rs::cv017_retryable_ingress_recovery_keeps_world_truth_public_in_memory`
executes this path on the controlled InMemory boundary. Runtime is used only
for the two `process_ingress` pump calls; all acceptance, status, history, and
Facet assertions use `LoomClient`.

`cv017()` itself follows the same public path and returns `Pass` only when a
running service exposes the Retryable/recovery lifecycle. The shared
`InMemoryServer`/`PgServer` composition has no worker, so it returns explicit
`Unavailable` after observing the public Accepted status and empty history/
Facet rather than claiming a retry Pass. The controlled
`cv017_public_bookkeeping_and_authority_survive_pg_restart_if_available` test
uses the real `PgServer` public boundary and an existing `Runtime` pump over a
second `PgStorage` connection to the same controlled PG18 database. It proves
public `Accepted -> Retryable(runtime_failure)` with unchanged history/Facet,
public seed recovery to `Completed(Committed)` with exactly one recovery
EventRef, and then obtains a new `PgServer` client after boundary restart to
re-read terminal status, ordered two-event history, and Facet value `2` with
no duplicate mutation.

## Verification record

Required commands for this candidate:

- `cargo fmt --all -- --check`
- `cargo check -p loom-validator --all-targets`
- `cargo clippy -p loom-validator --all-targets -- -D warnings`
- `cargo test -p loom-validator --test action_ingress -- --test-threads=1`
- `LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@127.0.0.1:15432/loom_control cargo test -p loom-validator --all-targets`
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json`
- `python3 tools/check_architecture.py`
- `python3 tools/check_storage_sql_ownership.py`
- `git diff --check`

The no-URL focused run records PostgreSQL as an explicit unavailable
prerequisite and is not PostgreSQL evidence. The explicit live URL run is the
required PostgreSQL execution; any unavailable service must remain an explicit
prerequisite/unavailable result, never a silent skip or Pass.

## Evidence and remaining boundary

CV-015 and CV-016 retain their existing public Event/Facet/history and durable
dedup conclusions. CV-017 now has public operational/status and World
authority evidence plus controlled InMemory and controlled PG18
Retryable/recovery evidence. The PG18 pump uses Runtime only as a test-local
worker driver; all acceptance, terminal status, history, Facet, and restart
observations remain through new/public `LoomClient` instances. No internal
table, Runtime state, log, or SQL read is acceptance evidence.

No central registry entry was added; `CV-017` remains local to T11 until the
central integration task decides its registration policy. Final V0
certification remains outside this leaf.
