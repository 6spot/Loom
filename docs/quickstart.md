# Loom V0 Quickstart — public surfaces only

This guide reproduces the supported V0 workflow from a clean checkout using only documented public surfaces: `loom-server` HTTP/SSE, `loom-client` and `loom-cli`. No Runtime/Storage imports and no direct database access are required. All commands use the current `ubuntu-latest` supported baseline; macOS is not required.

Pre-read: [`docs/architecture/README.md`](architecture/README.md) (authority map), [`docs/architecture/glossary.md`](architecture/glossary.md) (terminology), [`docs/operator-guide.md`](operator-guide.md) (concept deep-dive).

## 1. Prerequisites

### 1.1 Required stack

- **Linux/Ubuntu** — the mandatory CI and deployment baseline. The documented Compose path uses `ubuntu-latest`; macOS is not required and is not advertised as a gate (Amendment 0002 §4).
- **Rust 1.97.1** — pinned in `rust-toolchain.toml` (edition 2024). Install via `rustup toolchain install 1.97.1`.
- **PostgreSQL 18 + pgvector 0.8.6** — the only supported durable store. Image `pgvector/pgvector:0.8.6-pg18` (see `compose.yaml` and `compose.test-db.yaml`).
- **Docker Compose** — for the single-host durable stack.
- **Blob store** — local filesystem at `${LOOM_DATA_DIR:-./loom}/blobs`; PostgreSQL at `${LOOM_DATA_DIR:-./loom}/postgres`. No Docker named volume owns Loom data.

Check:

```bash
rustc --version   # rustc 1.97.1
cargo --version
docker compose version
```

### 1.2 Checkout and secrets

```bash
git clone https://github.com/6spot/Loom.git
cd Loom
cp .env.example .env
# Edit .env only to replace POSTGRES_PASSWORD outside development; do not commit the replacement.
cat .env.example
```

Key variables (all non-secret defaults in `.env.example`):

```text
POSTGRES_USER=loom
POSTGRES_PASSWORD=loom
POSTGRES_DB=loom_control
LOOM_DATABASE_URL=postgresql://loom:loom@localhost:5432/loom_control  # native; Compose overrides host to postgres:5432
LOOM_DATA_DIR=./loom
LOOM_BIND_ADDR=0.0.0.0:8080
LOOM_RUNTIME_REVISION_ID=loom-server
LOOM_CORE_BUILD_REF=loom-server-0.1.0
LOOM_WORKER_LEASE_MS=30000
LOOM_WORKER_RETRY_BACKOFF_MS=1000
LOOM_WORKER_POLL_MS=100
```

`LOOM_SERVER_URL`, `LOOM_BEARER_TOKEN`, `LOOM_ADMIN_TOKEN` are CLI-only (flags ` --server/--bearer-token/--admin-token` or env) and are never hard-coded. Provider credentials are not part of this composition root.

### 1.3 Migrations and Runtime Revision

Migrations live in `crates/loom-storage/migrations/` (DDL) and runtime SQL in `crates/loom-storage/sql/`. `loom-server` applies them at startup in order:

```text
connect to PostgreSQL → healthcheck → apply migrations → validate installed Capability registry → confirm/activate Runtime Revision → construct Runtime/Boundary/workers → bind HTTP listener
```

The Runtime Revision is the immutable, auditable publication of the current software composition:

- **Publish** at startup from `LOOM_RUNTIME_REVISION_ID` + `LOOM_CORE_BUILD_REF` + `loom_version` + installed Capability manifests (exact `implementation_id`/`version`/`loom_compatibility`) + optional execution/provider policy ids + `change_summary` + `semantic_behavior_changed`.
- **Activate** via isolated Admin CAS `AdminActivateRuntimeRevisionRequest { revision_id, expected_generation }` (generation prevents lost-update races).
- A new Revision only affects *future* Sessions whose World Runtime Binding is compatible; it never rewrites history, `World Time` or an existing Binding.

Inspect the active Revision after startup (see §3.8). Multiple Template revisions (§2.2) prove that later Templates only affect future Worlds.

## 2. Start the stack

### 2.1 Validate Compose

```bash
docker compose config
docker compose -f compose.test-db.yaml config --quiet  # test-only control DB
```

### 2.2 Bring up the durable stack

```bash
docker compose up --build
```

The durable root is `${LOOM_DATA_DIR:-./loom}`:

```text
./loom/postgres  -> PostgreSQL's /var/lib/postgresql
./loom/blobs     -> loom-server's /var/lib/loom/blobs
```

Change `LOOM_DATA_DIR` to relocate the tree while preserving `postgres/` and `blobs/` child names. The server container never receives the PostgreSQL child directory.

Wait for healthchecks (`pg_isready` and loom-server bound to `LOOM_BIND_ADDR`), then in a second terminal:

```bash
curl -Sf http://127.0.0.1:8080/v1/catalog | jq .
# or via CLI:
cargo run -p loom-cli -- --server http://127.0.0.1:8080 catalog --output human
```

For native startup without Compose:

```bash
LOOM_DATABASE_URL=postgresql://loom:loom@127.0.0.1:5432/loom_control \
LOOM_DATA_DIR=./loom \
cargo run -p loom-server
```

## 3. Public workflow — step by step

All examples below use `loom-cli` JSON output for scripting. Add `--output human` for pretty printing. Every authoritative rule is cited to its canonical doc.

### 3.1 Discover Templates and Catalog

```bash
# Global installed Capabilities/Actions/Facets and their descriptors
cargo run -p loom-cli -- catalog --output human
cargo run -p loom-cli -- catalog --world <world-id>   # per-World Binding-filtered Catalog

# Via client: CatalogService::catalog() / catalog_for_world(WorldId)
```

The global Catalog shows installed software (§3 Installed Capability). The per-World Catalog is already filtered by that World's immutable Runtime Binding — `registry_presence != World enablement` (glossary, world-runtime §3.1). The operator guide explains the three-way distinction `Installed vs Binding vs Assembly`.

User-facing setup uses only this discovery path; no direct SQL fixture mutation is supported. The neutral fixtures are `capabilities/loom-neutral` templates described in §2.2.

### 3.2 Create a World from a Template

```bash
# Create — the Template is consumed into ValidatedWorldBirthPlan (Amendment 0001 §7) atomically.
# Either --template-json inline or --template-file / --request-file is accepted (file is UX; server validates).
# Minimal neutral counter Template (world_time 0, one Capability requirement):
cargo run -p loom-cli -- world create \
  --template-json '{"id":"neutral.counter.v1","revision":1,"capabilities":[{"id":"neutral.counter","version":"^0.1.0"}],"configuration":{},"initial_world_time":0,"bootstrap_actions":[]}' \
  --output human

# The response contains world_id + timeline_id (the birth Timeline). Record them:
WORLD=<world-id-from-response>
TIMELINE=<timeline-id-from-response>

# The same descriptor can be supplied via a JSON file:
#   echo '{"id":"neutral.counter.v1","revision":1,"capabilities":[{"id":"neutral.counter","version":"^0.1.0"}],"configuration":{},"initial_world_time":0,"bootstrap_actions":[]}' > /tmp/template.json
#   cargo run -p loom-cli -- world create --template-file /tmp/template.json --output human
```

Installed neutral fixtures are in `capabilities/loom-neutral/src/lib.rs` (`registry()`) — `neutral.counter` and `neutral.observer` with dependency `observer ^0.1.0 → counter ^0.1.0`. A variant that adds `neutral.observer` demonstrates installed-but-disabled semantics (see `docs/operator-guide.md` §1).

A Template's `TemplateCapabilityRequirement[]` (e.g. `neutral.counter ^0.1.0`, `neutral.observer ^0.1.0`) becomes the World's immutable Runtime Binding. Future Template revisions only affect future Worlds; existing Worlds are not rewritten. Installed-but-disabled semantics: a Capability may be present in the Registry/Revision yet not enabled for a World whose Binding excludes it.

The server validates Templates Runtime-side (`ValidatedWorldBirthPlan`); CLI file/inline JSON is transport only.

### 3.3 Invoke an Action and inspect State/History/Catalog

```bash
# Invoke — Action type comes from the Template/Catalog; payload matches the Action's input schema:
cargo run -p loom-cli -- action invoke \
  --world $WORLD --timeline $TIMELINE \
  --action neutral.counter.seed \
  --input '{"event_id":"<uuid>","entity_id":"<uuid>","value":41}' \
  --output human

# Increment the same Entity:
cargo run -p loom-cli -- action invoke \
  --world $WORLD --timeline $TIMELINE \
  --action neutral.counter.increment \
  --input '{"event_id":"<uuid>","entity_id":"<same-entity>","amount":1}' \
  --output human

# Current State — Entity/Relationship Facet at StateRevision (materialized projection):
cargo run -p loom-cli -- facet get \
  --world $WORLD --timeline $TIMELINE \
  --owner-kind entity --owner <entity-id> --facet-type neutral.counter.value \
  --output human

# Timeline snapshot (World Time / logical status / budget / ancestry):
cargo run -p loom-cli -- timeline inspect --world $WORLD --timeline $TIMELINE --output human

# History — committed Events + frozen Effects (World History):
cargo run -p loom-cli -- history events --world $WORLD --timeline $TIMELINE --limit 20 --output human
cargo run -p loom-cli -- history event --world $WORLD --timeline $TIMELINE --event-ref <timeline:uuid/event:uuid> --output human

# Trajectory / causality (Entity/Relationship history, causes/effects walk):
cargo run -p loom-cli -- trajectory entity --world $WORLD --timeline $TIMELINE --entity <entity-id> --output human
cargo run -p loom-cli -- history causes --world $WORLD --timeline $TIMELINE --event-ref <ref> --depth 8 --output human
cargo run -p loom-cli -- history effects --world $WORLD --timeline $TIMELINE --event-ref <ref> --depth 8 --output human
cargo run -p loom-cli -- history walk --world $WORLD --timeline $TIMELINE --from <ref> --direction causes --depth 32 --output human

# Catalog — Binding-aware re-inspection:
cargo run -p loom-cli -- catalog --world $WORLD --output human
```

`ApiErrorCode` maps to exit codes 10–16 (`InvalidRequest 10`, `NotFound 11`, `Conflict 12`, `Unavailable 13`, `Unauthorized 14`, `Forbidden 15`, `Internal 16`). CLI local validation is UX-only; the server remains authority — a rejected Action (`ResolveOutcome::Rejected`) is a correct no-world-change completion of the Session, reported in provenance.

### 3.4 Submit Ingress and tail/resume the Change Feed

```bash
# Durable, idempotent external envelope (Ingress is not yet World Truth; it enters normal Action authority).
# The envelope is transport-stable JSON; the same can be supplied via --file ./ingress.json:
cargo run -p loom-cli -- ingress submit --json '{"idempotency_key":"<stable-key>","target":{"world_id":"'"$WORLD"'","timeline_id":"'"$TIMELINE"'"},"invocation":{"action_type":"neutral.counter.increment","input":{"event_id":"<uuid>","entity_id":"<same-entity>","amount":2}}}' \
  --output human

# Status — idempotencyKey + IngressStatus (Pending/Completed/Conflict/Failed):
cargo run -p loom-cli -- ingress status --idempotency-key <stable-key> --output human

# Tail the committed Change Feed (SSE-backed Subscription):
cargo run -p loom-cli -- feed tail --world $WORLD --timeline $TIMELINE --output human
# Subscribe with cursor for resumable reads (cursor is EventSeq+StateRevision opaque token):
cargo run -p loom-cli -- feed subscribe --world $WORLD --timeline $TIMELINE --cursor '<cursor-json>' --output human
```

A durable `IdempotencyKey` guarantees at-most-once acceptance; the committed feed only contains Runtime-committed Events, never accepted-but-uncommitted envelopes. Resume uses the committed `ChangeFeedCursor` (returned by `SubscriptionService`); no client-side checkpoint marker replaces server history.

### 3.5 Scheduler progression and World Time

```bash
# Drive head Work — once a counter Reaction Work is scheduled by the previous increment:
cargo run -p loom-cli -- admin timeline status --world $WORLD --timeline $TIMELINE --output human
# When quiescent (no Pending semantically due Work), advance World Time explicitly:
cargo run -p loom-cli -- admin world-time advance \
  --world $WORLD --timeline $TIMELINE \
  --expected-head-seq <seq> --expected-state-rev <rev> \
  --current 0 --next 1 \
  --output human
cargo run -p loom-cli -- timeline inspect --world $WORLD --timeline $TIMELINE --output human
```

Key laws (operator guide for deep-dive):

- Durable Work ordering is `(effective_due_world_time, logical_schedule_order)` per Timeline; later Work never claims ahead of a semantically due logical head. `SKIP LOCKED` is only across independent Timeline heads.
- Only `Scheduler`-managed `Pending` head Work at `effective_due_world_time <= Timeline.world_time` may claim; platform `lease`/`retry available_at` never creates semantic due-ness nor advances `World Time`.
- `Chronology Budget` is Timeline Logical State (`chronology_consumed` committed alongside Work completion); exhausting the budget at a fixed `WorldInstant` stops further automatic execution but never forces `World Time` past due work.
- A fresh determination uses `WorkTerminalization` authority (`AdminTerminalizeWorkRequest`) for the explicit `Pending → Dead/Cancelled` Logical Commit when `FailurePolicy` or operator policy requires it.

Leave the server running and re-inspect with `history events` / `timeline inspect`; the Logical Journal replays deterministically through CAS without re-running resolvers.

### 3.6 Replay

Replay reconstructs both Materialized State and Timeline Logical State (including `World Time` and `chronology_consumed`) for any committed `TimelineVersion` without re-running Capability code:

```bash
# List committed Events; each Event's seq+revision is a replayable position:
cargo run -p loom-cli -- history events --world $WORLD --timeline $TIMELINE --limit 100

# Inspect the historical materialized projection via pinned reads at that version:
cargo run -p loom-cli -- facet get --world $WORLD --timeline $TIMELINE --owner-kind entity --owner <entity-id> --facet-type neutral.counter.value
```

`replay != rerun`: replay is deterministic read-only reconstruction of committed history (no new `Execution Assembly`, no new Events); rerun would re-resolve with a potentially different software Revision and must not be confused with history truth. Full isolation evidence: `crates/loom-storage/tests/postgres_work.rs`, `crates/loom-storage/tests/pinned_reads.rs`.

### 3.7 Fork (branch isolation)

```bash
# Fork from current head (default):
cargo run -p loom-cli -- timeline fork --world $WORLD --timeline $TIMELINE --output human
# Or from an explicit committed version:
cargo run -p loom-cli -- timeline fork --world $WORLD --timeline $TIMELINE --source-version 3:5 --output human
CHILD_TIMELINE=<timeline-id-from-fork-response>

# The child preserves the parent Binding and clones branch-local Pending Works; Platform Operational State (lease/fence) is not forked:
cargo run -p loom-cli -- timeline inspect --world $WORLD --timeline $CHILD_TIMELINE --output human
cargo run -p loom-cli -- facet get --world $WORLD --timeline $CHILD_TIMELINE --owner-kind entity --owner <entity-id> --facet-type neutral.counter.value --output human

# Mutations on the child never affect the parent; provenance records ancestry:
cargo run -p loom-cli -- action invoke --world $WORLD --timeline $CHILD_TIMELINE --action neutral.counter.increment --input '{"event_id":"<uuid>","entity_id":"<same-entity>","amount":5}' --output human
cargo run -p loom-cli -- history events --world $WORLD --timeline $CHILD_TIMELINE --output human
cargo run -p loom-cli -- history events --world $WORLD --timeline $TIMELINE --output human
```

`TimelineAncestry`/`TimelineVersion` lineage is immutable and queryable via `history` causality. Cross-branch `Event`/`call` provenance never leaks.

### 3.8 Inspect provenance (Runtime Revision / Session)

```bash
# Revisions — active pointer with CAS generation, list and single read:
cargo run -p loom-cli -- admin revision list --output human
cargo run -p loom-cli -- admin revision get --revision-id loom-server --output human
cargo run -p loom-cli -- admin revision activate --revision-id loom-server --expected-generation 0 --output human  # CAS-gated

# Sessions — lifecycle Started/Committed/NoChange/Rejected/Failed/Blocked with safe provenance projection:
cargo run -p loom-cli -- admin session get --session-id <uuid> --output human
cargo run -p loom-cli -- admin session for-event --event-ref <timeline:uuid/event:uuid> --output human

# Provenance links Event → producing Session → Runtime Revision/implementation/read/call/entropy evidence:
cargo run -p loom-cli -- history event --world $WORLD --timeline $TIMELINE --event-ref <ref> --output human  # shows producing session id when linked
```

Every successful `ExecutionSession` was pinned to `TimelineTarget` + `TimelineVersion` + `World Runtime Binding` + `Runtime Revision` + exact compatible Capability implementations (the `Execution Assembly`) at session start. Stale cognition / fenced-out resolver results cannot commit; a CAS loser produces a `Discarded` observation retained in provenance.

### 3.9 Deterministic Agency Wake

```bash
# Schedule an explicit Agency Wake (Scheduler-managed durable Work with Agency target).
# The same wake can be supplied via --file with AdminScheduleAgencyWakeRequest JSON:
cargo run -p loom-cli -- admin agency schedule-wake --world $WORLD --timeline $TIMELINE --agent <entity-id> --cognition '{"executor":"deterministic","policy":"resample"}' --output human

# Drive the Wake (Scheduler claims the due wake head, Runtime builds Binding-checked AgentWorldView, runs Cognition, routes Decision::Act back through normal Capability authority):
cargo run -p loom-cli -- admin timeline status --world $WORLD --timeline $TIMELINE --output human
cargo run -p loom-cli -- admin session get --session-id <wake-session-id> --output human

# CAS resample policy visibility — after a stale cognition loses CAS, the observation disposition shows Discarded vs Fresh/Reused:
cargo run -p loom-cli -- admin session get --session-id <wake-session-id> --output human  # inspect cognitive_observations[].disposition/policy
```

- `AgentWorldView` is constructed through Runtime mediation, never by direct Storage access; its visibility subset is Binding-checked, and its `ContextBudget` is enforced before cognition.
- `Decision::Act(ActionInvocation)` re-enters normal `Action → Resolution → ValidatedResolution → Logical Commit` authority; semantic rejection of the Act completes the same Wake as `NoChange` (no second attempt replaces the observed result; reconsideration is a new Wake — Amendment 0003 §3).
- Default policy after CAS loss is `Resample` (re-invoke cognition with fresh pinned version, 2× cost); `ReuseDeterministic` (1×) is explicit, provenance-visible and revalidated against the fresh coordinate. See `docs/operator-guide.md` §Agent visibility/CAS and `docs/capacity-envelope.md` for measured cost.

The supported V0 Agency example is the deterministic fake (`DeterministicCognitiveExecutor` via `loom-neutral`). Real vendor LLM integration remains non-blocking / deferred — it must arrive as a reviewed provider adapter with application-owned credentials, not as part of the V0 composition root.

### 3.10 Restart and resume

```bash
# Restart is durable — all truth is in PostgreSQL + blob store:
docker compose restart loom-server
# Or native: stop loom-server (Ctrl-C / SIGTERM) then run it again with the same LOOM_DATABASE_URL/LOOM_DATA_DIR.

# Verify after restart: history, feed, and scheduler all resume from committed position:
cargo run -p loom-cli -- history events --world $WORLD --timeline $TIMELINE --output human
cargo run -p loom-cli -- feed subscribe --world $WORLD --timeline $TIMELINE --cursor '<last-cursor>' --output human
cargo run -p loom-cli -- timeline inspect --world $WORLD --timeline $TIMELINE --output human

# Expired leases are reclaimable; stale fences cannot retry/complete/terminalize:
cargo run -p loom-cli -- admin timeline missing-implementation --world $WORLD --timeline $TIMELINE --output human
cargo run -p loom-cli -- admin work terminalize --world $WORLD --timeline $TIMELINE --work-id <work-id> --state Dead --output human
```

The worker helper checks the shutdown signal before each `drive_timeline` step; an active step is allowed to finish, so graceful stop does not revoke a live claim mid-commit. Process death after claim leaves the Work `Pending` with an operational lease; after lease expiry a later worker reclaims it with a newer fence. No in-process restart marker or Runtime-global mutex is required.

## 4. No-secret local examples

- Copy `.env.example` → `.env`; the committed defaults run locally with `POSTGRES_USER=loom`, `POSTGRES_PASSWORD=loom` (local-test-only).
- Replace `POSTGRES_PASSWORD` outside development; never commit provider/LLM credentials.
- Example Templates and Ingress envelopes are JSON files submitted through the CLI/API — never through direct SQL fixture mutation (`loom-storage` owns migrations/SQL exclusively).

## 5. Validated commands checklist

Every command above uses a supported public surface and has a corresponding fixture/integration path in the workspace:

- Server: `cargo run -p loom-server` / `docker compose up` → `SystemClock` + `PgStorage` + `loom-boundary` → `Runtime::drive_timeline` via bounded `SchedulerWorker`.
- Client: `loom-client` (`crates/loom-client`) — HTTP/JSON + SSE over `loom-api`.
- CLI: `cargo run -p loom-cli -- --help` (all subcommands enumerated in `apps/loom-cli/src/lib.rs`); `cargo test -p loom-cli --all-features` (deterministic JSON/cursors, `ApiErrorCode` exit codes 10–16, feed resume/fork/provenance/Admin workflows via `loom-boundary` + `InMemoryStore`).
- Persistence: `bash tools/postgres-test.sh up` then `cargo test --workspace --all-features` (or `bash tools/test.sh --workspace --all-features` which starts/uses the `loom_control` service at `postgresql://loom:loom@127.0.0.1:15432/loom_control` if `LOOM_TEST_POSTGRES_URL` is unset).

For full operator/developer deep-dives and measured capacity evidence, continue to `docs/operator-guide.md`, `docs/developer-guide.md` and `docs/capacity-envelope.md`.
