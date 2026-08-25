# Loom V0 Quickstart — public surfaces only

This guide reproduces the supported V0 workflow from a clean checkout using only documented public surfaces: `loom-server` HTTP/SSE, `loom-client` and `loom-cli`. No Runtime/Storage imports and no direct database access are required. All commands use the current `ubuntu-latest` supported baseline; macOS is not required.

> **Notation:** Global flags `--output/--server/--admin-token` are parsed on `Cli` before the subcommand (see `apps/loom-cli/src/lib.rs:66-68`). Every example puts them **before** the subcommand: `loom --output human catalog ...` → `cargo run -p loom-cli -- --output human catalog ...`. Writing `loom catalog --output human` fails with `unexpected argument '--output'`. All examples below have been swept with `cargo run -p loom-cli -- <subcommand> --help` and with serde deserialization for JSON payloads.

Pre-read: [`docs/architecture/README.md`](architecture/README.md) (authority map), [`docs/architecture/glossary.md`](architecture/glossary.md) (terminology), [`docs/operator-guide.md`](operator-guide.md) (concept deep-dive). Neutral fixtures and end-to-end example walks: [`examples/neutral-v0/README.md`](../examples/neutral-v0/README.md).

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
# Admin token is NOT in .env.example; set it for every admin command (no hard-coded secret):
# LOOM_ADMIN_TOKEN=<generate-and-export>
# Scheduler target is NOT set by default (see §3.5):
# LOOM_SCHEDULER_WORLD_ID=
# LOOM_SCHEDULER_TIMELINE_ID=
```

`LOOM_SERVER_URL`, `LOOM_BEARER_TOKEN`, `LOOM_ADMIN_TOKEN` are CLI-only (global flags `--server/--bearer-token/--admin-token` or env) and are never hard-coded. Provider credentials are not part of this composition root.

### 1.3 Migrations and Runtime Revision

Migrations live in `crates/loom-storage/migrations/` (DDL) and runtime SQL in `crates/loom-storage/sql/`. `loom-server` applies them at startup in order:

```text
connect to PostgreSQL → healthcheck → apply migrations → validate installed Capability registry → confirm/activate Runtime Revision → construct Runtime/Boundary/workers → bind HTTP listener
```

The Runtime Revision is the immutable, auditable publication of the current software composition:

- **Publish** at startup from `LOOM_RUNTIME_REVISION_ID` + `LOOM_CORE_BUILD_REF` + `loom_version` + installed Capability manifests (exact `implementation_id`/`version`/`loom_compatibility`) + optional execution/provider policy ids + `change_summary` + `semantic_behavior_changed`.
- **Activate** via isolated Admin CAS `AdminActivateRuntimeRevisionRequest { revision_id, expected_generation }` (generation prevents lost-update races).
- A new Revision only affects *future* Sessions whose World Runtime Binding is compatible; it never rewrites history, `World Time` or an existing Binding.

Inspect the active Revision after startup (see §3.8, requires `LOOM_ADMIN_TOKEN`).

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
# or via CLI (global --output before subcommand):
cargo run -p loom-cli -- --server http://127.0.0.1:8080 --output human catalog
```

For native startup without Compose:

```bash
LOOM_DATABASE_URL=postgresql://loom:loom@127.0.0.1:5432/loom_control \
LOOM_DATA_DIR=./loom \
cargo run -p loom-server
```

> **Scheduler note (D-004):** The default `.env.example` leaves `LOOM_SCHEDULER_WORLD_ID`/`LOOM_SCHEDULER_TIMELINE_ID` empty and `compose.yaml` does not set them. `apps/loom-server/src/config.rs:367-380` returns `None` and `application.rs:491-499` only creates a worker when the target exists. The default Compose therefore **does not auto-drive** Scheduler Work. After creating a World (§3.2), set those two variables to the new World's IDs and restart the server (§3.5) before expecting Work/World Time progress.

> **Admin note (D-007):** The default server uses `RequireAdminAuthorization` (`application.rs:478-481`) and the boundary requires non-empty `x-loom-admin-authorization` (`loom-boundary/src/lib.rs:315-332`). Every `admin` command below includes `--admin-token` (global, before subcommand) with a non-hard-coded value via `LOOM_ADMIN_TOKEN` environment or flag. Without it the server returns `Unauthorized`.

## 3. Public workflow — step by step

All examples use `loom-cli` JSON output for scripting. Global `--output human` is placed **before** the subcommand; subcommand-specific flags follow the subcommand verb. Every authoritative rule is cited to its canonical doc.

### 3.1 Catalog (global vs per-World)

`CatalogSnapshot` (`crates/loom-api/src/lib.rs:1913-1942`) currently exposes Capability/Action/Facet/Relationship/Event/Work/Reaction/index descriptors only. It has no Template field, and `CatalogService`/`loom-boundary` expose only `catalog` and `catalog-for-world`. Template discovery via catalog is therefore **not available at head** — use caller-constructed `WorldTemplateDescriptor` (§3.2) instead.

```bash
# Global installed Capabilities/Actions/Facets and their descriptors
cargo run -p loom-cli -- --output human catalog
cargo run -p loom-cli -- --server http://127.0.0.1:8080 --output human catalog

# Per-World Binding-filtered Catalog (requires a WorldId from §3.2):
cargo run -p loom-cli -- --output human catalog --world-id 00000000-0000-0000-0000-000000000001

# Via client: CatalogService::catalog() / catalog_for_world(WorldId)
```

The global Catalog shows installed software (Installed Capability). The per-World Catalog is already filtered by that World's immutable Runtime Binding — `registry_presence != World enablement` (glossary, world-runtime §3.1). The operator guide explains the three-way distinction `Installed vs Binding vs Assembly`.

User-facing setup uses only this discovery path; no direct SQL fixture mutation is supported. The neutral fixtures `capabilities/loom-neutral` expose `neutral.counter` and `neutral.observer` (with `observer ^0.1.0 → counter ^0.1.0` dependency) plus `neutral.link.membership` (Relationship), `neutral.blob.reference` (Facet) and `neutral.counter.semantic` (semantic index) via `registry()`; supported example Templates are in `examples/neutral-v0/templates/revision-1.json` and `revision-2.json` (see `examples/neutral-v0/README.md` and `tests/loom-composition/neutral_v0_workflows.rs`).

### 3.2 Create a World from a `WorldTemplateDescriptor`

There is no Template catalog at head. A `WorldTemplateDescriptor` is constructed by the caller (TemplateId + revision + `TemplateCapabilityRequirement[]` + `initial_world_time`) and validated Runtime-side into `ValidatedWorldBirthPlan` (Amendment 0001 §7).

```bash
# Minimal neutral counter Template (world_time 0, one Capability requirement).
# Supported example Templates with deterministic IDs/world-time are in examples/neutral-v0/templates/:
#   cargo run -p loom-cli -- --output human world create --template-file examples/neutral-v0/templates/revision-1.json
#   cargo run -p loom-cli -- --output human world create --template-file examples/neutral-v0/templates/revision-2.json
# --template-json / --template-file accept a WorldTemplateDescriptor;
# --request-file must be a CreateWorldFromTemplateRequest with top-level {"template": descriptor} (server validates both forms).
cargo run -p loom-cli -- --output human world create \
  --template-json '{"id":"neutral.counter.v1","revision":1,"capabilities":[{"id":"neutral.counter","version":"^0.1.0"}],"configuration":{},"initial_world_time":0,"bootstrap_actions":[]}'

# The response contains world_id + timeline_id (the birth Timeline). Record them:
WORLD=00000000-0000-0000-0000-000000000010
TIMELINE=00000000-0000-0000-0000-000000000011
# Use the actual UUIDs returned by the previous command for the following steps.

# The same descriptor can be supplied via a JSON file:
#   echo '{"id":"neutral.counter.v1","revision":1,"capabilities":[{"id":"neutral.counter","version":"^0.1.0"}],"configuration":{},"initial_world_time":0,"bootstrap_actions":[]}' > /tmp/template.json
#   cargo run -p loom-cli -- --output human world create --template-file /tmp/template.json
# Or as a full request with top-level template (for --request-file):
#   echo '{"template":{"id":"neutral.counter.v1","revision":1,"capabilities":[{"id":"neutral.counter","version":"^0.1.0"}],"configuration":{},"initial_world_time":0,"bootstrap_actions":[]}}' > /tmp/request.json
#   cargo run -p loom-cli -- --output human world create --request-file /tmp/request.json
```

Installed neutral fixtures are in `capabilities/loom-neutral/src/lib.rs` (`registry()`) — `neutral.counter` and `neutral.observer` with dependency `observer ^0.1.0 → counter ^0.1.0`, plus `neutral.link.membership` (Relationship), `neutral.blob.reference` and `neutral.counter.semantic`. Two supported example Templates `examples/neutral-v0/templates/revision-1.json` (counter profile, one bootstrap, `initial_world_time: 11`) and `revision-2.json` (observer profile, two bootstraps, `initial_world_time: 22`) visibly differ: a World created from revision 1 never mutates when revision 2 is later used for a new World (future-World-only change), and an `neutral.observer.observe` Action globally installed is `Unavailable` for a revision-1 World (installed-but-disabled; see `examples/neutral-v0/README.md` and `tests/loom-composition/neutral_v0_workflows.rs`).

A Template's `TemplateCapabilityRequirement[]` (e.g. `neutral.counter ^0.1.0`) becomes the World's immutable Runtime Binding. Future Template revisions only affect future Worlds; existing Worlds are not rewritten. Installed-but-disabled semantics: a Capability may be present in the Registry/Revision yet not enabled for a World whose Binding excludes it.

The server validates Templates Runtime-side (`ValidatedWorldBirthPlan`); CLI file/inline JSON is transport only.

### 3.3 Invoke an Action and inspect State/History/Catalog

```bash
# Invoke — Action type comes from the Template/Catalog; payload matches the Action's input schema.
# Use --world/--timeline (required) plus --action and --input (or --input-file / --request-file / --request-json):
cargo run -p loom-cli -- --output human action invoke \
  --world $WORLD --timeline $TIMELINE \
  --action neutral.counter.seed \
  --input '{"event_id":"00000000-0000-0000-0000-000000000020","entity_id":"00000000-0000-0000-0000-000000000021","value":41}'

# Increment the same Entity:
cargo run -p loom-cli -- --output human action invoke \
  --world $WORLD --timeline $TIMELINE \
  --action neutral.counter.increment \
  --input '{"event_id":"00000000-0000-0000-0000-000000000022","entity_id":"00000000-0000-0000-0000-000000000021","amount":1}'

# Current State — Entity/Relationship Facet at StateRevision (materialized projection):
cargo run -p loom-cli -- --output human facet get \
  --world $WORLD --timeline $TIMELINE \
  --owner 00000000-0000-0000-0000-000000000021 --owner-kind entity --facet-type neutral.counter.value

# Timeline snapshot (World Time / logical status / budget / ancestry):
cargo run -p loom-cli -- --output human timeline inspect --world $WORLD --timeline $TIMELINE

# History — committed Events + frozen Effects (World History):
cargo run -p loom-cli -- --output human history events --world $WORLD --timeline $TIMELINE --limit 20
# Single event (use --timeline + --event-id or --event-ref "timeline:uuid/event:uuid"):
cargo run -p loom-cli -- --output human history event --timeline $TIMELINE --event-id 00000000-0000-0000-0000-000000000020

# Trajectory / causality (Entity trajectory uses --entity-id; causes/effects use --timeline + --event-id; walk uses --max-depth):
cargo run -p loom-cli -- --output human trajectory entity --world $WORLD --timeline $TIMELINE --entity-id 00000000-0000-0000-0000-000000000021
cargo run -p loom-cli -- --output human history causes --timeline $TIMELINE --event-id 00000000-0000-0000-0000-000000000022
cargo run -p loom-cli -- --output human history effects --timeline $TIMELINE --event-id 00000000-0000-0000-0000-000000000022
cargo run -p loom-cli -- --output human history walk --timeline $TIMELINE --event-id 00000000-0000-0000-0000-000000000020 --max-depth 8 --limit 100 --direction causes

# Catalog — Binding-aware re-inspection (per-World Catalog uses --world-id):
cargo run -p loom-cli -- --output human catalog --world-id $WORLD
```

`ApiErrorCode` maps to exit codes 10–16 (`InvalidRequest 10`, `NotFound 11`, `Conflict 12`, `Unavailable 13`, `Unauthorized 14`, `Forbidden 15`, `Internal 16`). CLI local validation is UX-only; the server remains authority — a rejected Action (`ResolveOutcome::Rejected`) is a correct no-world-change completion of the Session, reported in provenance.

> **Relationship and blob/semantic (supported via neutral fixtures):** `capabilities/loom-neutral` exposes `neutral.link.membership` (Relationship), `neutral.blob.reference` and `neutral.counter.semantic`. After seeding a second participant via the public Action, create and inspect a Relationship (no direct storage/SQL):
> ```bash
> cargo run -p loom-cli -- --output human action invoke --world $WORLD --timeline $TIMELINE --action neutral.counter.seed --input '{"event_id":"00000000-0000-0000-0000-000000005183","entity_id":"00000000-0000-0000-0000-000000005102","value":7}'
> cargo run -p loom-cli -- --output human action invoke --world $WORLD --timeline $TIMELINE --action neutral.link.create --input '{"event_id":"00000000-0000-0000-0000-000000005184","relationship_id":"00000000-0000-0000-0000-000000006001","left_entity":"00000000-0000-0000-0000-000000000021","right_entity":"00000000-0000-0000-0000-000000005102"}'
> cargo run -p loom-cli -- --output human trajectory relationship --world $WORLD --timeline $TIMELINE --relationship-id 00000000-0000-0000-0000-000000006001
> cargo run -p loom-cli -- --output human action invoke --world $WORLD --timeline $TIMELINE --action neutral.blob.attach --input '{"event_id":"00000000-0000-0000-0000-000000005172","entity_id":"00000000-0000-0000-0000-000000000021","hash":"sha256:example","media_type":"text/plain"}'
> ```
> Semantic retrieval is demonstrated via `examples/neutral-v0/README.md` and `tests/loom-composition/neutral_v0_workflows.rs` (real `SemanticProjectionStore` registration/rebuild/query, not just catalog discovery). `trajectory entity` above remains the primary Entity example.

### 3.4 Submit Ingress and tail/resume the Change Feed

`IngressEnvelope` (`crates/loom-api/src/lib.rs:599-614`) requires `ingress_id`, `idempotency_key`, `provenance` (with `source`), `target` (`world_id`/`timeline_id`), `authorization`, `time_metadata` and `invocation` with field `action` (not `action_type`). The CLI accepts a full envelope via `--file`/`--json` or convenience fields `--ingress-id`/`--idempotency-key`/`--world`/`--timeline`/`--action`/`--input`.

A directly parseable full-envelope example (serde-validated, uses `invocation.action`):

```bash
# Valid full envelope JSON (all required fields present; authorization/time_metadata may be {}):
cargo run -p loom-cli -- --output human ingress submit --json '{
  "ingress_id":"00000000-0000-0000-0000-000000000030",
  "idempotency_key":"quickstart-key-1",
  "provenance":{"source":"quickstart","metadata":{}},
  "target":{"world_id":"'"$WORLD"'","timeline_id":"'"$TIMELINE"'"},
  "authorization":{},
  "time_metadata":{},
  "invocation":{"action":"neutral.counter.increment","input":{"event_id":"00000000-0000-0000-0000-000000000031","entity_id":"00000000-0000-0000-0000-000000000021","amount":2}}
}'

# Convenience-field form (avoids hand-crafting provenance/authorization):
cargo run -p loom-cli -- --output human ingress submit \
  --ingress-id 00000000-0000-0000-0000-000000000032 --idempotency-key quickstart-key-2 \
  --world $WORLD --timeline $TIMELINE --action neutral.counter.increment \
  --input '{"event_id":"00000000-0000-0000-0000-000000000033","entity_id":"00000000-0000-0000-0000-000000000021","amount":2}'

# Status — query by ingress_id (not idempotency_key):
cargo run -p loom-cli -- --output human ingress status --ingress-id 00000000-0000-0000-0000-000000000030

# Tail the committed Change Feed (SSE-backed Subscription). Use --after + --limit for pagination; there is no --cursor flag (use --request-file/--request-json for a full SubscriptionRequest with resume_from):
cargo run -p loom-cli -- --output human feed subscribe --world $WORLD --timeline $TIMELINE --limit 100
cargo run -p loom-cli -- --output human feed tail --world $WORLD --timeline $TIMELINE --after 1 --limit 100
# Resume from a durable cursor via a full SubscriptionRequest JSON (requires --world/--timeline even with --request-file; cursor inside resume_from holds the same target + after):
#   echo '{"target":{"world_id":"'"$WORLD"'","timeline_id":"'"$TIMELINE"'"},"resume_from":{"target":{"world_id":"'"$WORLD"'","timeline_id":"'"$TIMELINE"'"},"after":2},"limit":100}' > /tmp/sub.json
#   cargo run -p loom-cli -- --output human feed subscribe --world $WORLD --timeline $TIMELINE --request-file /tmp/sub.json
```

A durable `IdempotencyKey` guarantees at-most-once acceptance; the committed feed only contains Runtime-committed Events, never accepted-but-uncommitted envelopes. Resume uses `SubscriptionRequest` with `resume_from: ChangeFeedCursor{target, after: EventSeq}` (or `--after`/`--limit` for bounded pagination) via the API, not a client-side `--cursor` flag.

### 3.5 Scheduler progression and World Time

The default Compose does **not** run a Scheduler worker until `LOOM_SCHEDULER_WORLD_ID` and `LOOM_SCHEDULER_TIMELINE_ID` are set (see §2.2 note). After creating the World, configure the target and restart the server:

```bash
# One-time Scheduler target setup (non-secret, no hard-coded secret):
echo "LOOM_SCHEDULER_WORLD_ID=$WORLD" >> .env
echo "LOOM_SCHEDULER_TIMELINE_ID=$TIMELINE" >> .env
docker compose up -d --build loom-server
# Native: export LOOM_SCHEDULER_WORLD_ID=$WORLD LOOM_SCHEDULER_TIMELINE_ID=$TIMELINE; cargo run -p loom-server

# Observe scheduled Reaction Work (counter increment schedules Immediate Work; Admin token required):
cargo run -p loom-cli -- --admin-token $LOOM_ADMIN_TOKEN --output human admin timeline status --world $WORLD --timeline $TIMELINE
# This command is read-only; it does not drive the Scheduler. Driving requires the configured worker above.
# The server's bounded worker calls Runtime::drive_timeline on the configured Timeline when the target is present.

# When quiescent (no Pending semantically due Work), advance World Time explicitly (requires Admin token, global before subcommand):
export LOOM_ADMIN_TOKEN=$(openssl rand -hex 16)  # generate; do not hard-code; must match server's LOOM_ADMIN_TOKEN
cargo run -p loom-cli -- --admin-token $LOOM_ADMIN_TOKEN --output human admin world-time advance \
  --world $WORLD --timeline $TIMELINE \
  --expected-head-seq 2 --expected-state-rev 2 \
  --current 0 --next 1
cargo run -p loom-cli -- --output human timeline inspect --world $WORLD --timeline $TIMELINE
```

Key laws (operator guide for deep-dive):

- Durable Work ordering is `(effective_due_world_time, logical_schedule_order)` per Timeline; later Work never claims ahead of a semantically due logical head. `SKIP LOCKED` is only across independent Timeline heads.
- Only `Scheduler`-managed `Pending` head Work at `effective_due_world_time <= Timeline.world_time` may claim; platform `lease`/`retry available_at` never creates semantic due-ness nor advances `World Time`.
- `Chronology Budget` is Timeline Logical State (`chronology_consumed` committed alongside Work completion); exhausting the budget at a fixed `WorldInstant` stops further automatic execution but never forces `World Time` past due work.
- A fresh determination uses `WorkTerminalization` authority (`AdminTerminalizeWorkRequest` with `--expected-head-seq`/`--expected-state-rev`) for the explicit `Pending → Dead/Cancelled` Logical Commit when `FailurePolicy` or operator policy requires it.

Leave the server running and re-inspect with `history events` / `timeline inspect`; the Logical Journal replays deterministically through CAS without re-running resolvers.

### 3.6 Replay

Replay reconstructs both Materialized State and Timeline Logical State (including `World Time` and `chronology_consumed`) for any committed `TimelineVersion` without re-running Capability code:

```bash
# List committed Events; each Event's seq+revision is a replayable position:
cargo run -p loom-cli -- --output human history events --world $WORLD --timeline $TIMELINE --limit 100

# Inspect the historical materialized projection via pinned reads at that version:
cargo run -p loom-cli -- --output human facet get --world $WORLD --timeline $TIMELINE --owner 00000000-0000-0000-0000-000000000021 --owner-kind entity --facet-type neutral.counter.value
```

`replay != rerun`: replay is deterministic read-only reconstruction of committed history (no new `Execution Assembly`, no new Events); rerun would re-resolve with a potentially different software Revision and must not be confused with history truth. Full isolation evidence: `crates/loom-storage/tests/postgres_work.rs`, `crates/loom-storage/tests/pinned_reads.rs`.

### 3.7 Fork (branch isolation)

```bash
# Fork from current head (default):
cargo run -p loom-cli -- --output human timeline fork --world $WORLD --timeline $TIMELINE
# Or from an explicit committed version:
cargo run -p loom-cli -- --output human timeline fork --world $WORLD --timeline $TIMELINE --source-version 3:5
CHILD_TIMELINE=00000000-0000-0000-0000-000000000040

# The child preserves the parent Binding and clones branch-local Pending Works; Platform Operational State (lease/fence) is not forked:
cargo run -p loom-cli -- --output human timeline inspect --world $WORLD --timeline $CHILD_TIMELINE
cargo run -p loom-cli -- --output human facet get --world $WORLD --timeline $CHILD_TIMELINE --owner 00000000-0000-0000-0000-000000000021 --owner-kind entity --facet-type neutral.counter.value

# Mutations on the child never affect the parent; provenance records ancestry:
cargo run -p loom-cli -- --output human action invoke --world $WORLD --timeline $CHILD_TIMELINE --action neutral.counter.increment --input '{"event_id":"00000000-0000-0000-0000-000000000041","entity_id":"00000000-0000-0000-0000-000000000021","amount":5}'
cargo run -p loom-cli -- --output human history events --world $WORLD --timeline $CHILD_TIMELINE
cargo run -p loom-cli -- --output human history events --world $WORLD --timeline $TIMELINE
```

`TimelineAncestry`/`TimelineVersion` lineage is immutable and queryable via `history` causality. Cross-branch `Event`/`call` provenance never leaks.

### 3.8 Inspect provenance (Runtime Revision / Session)

All `admin` commands require `--admin-token` (global, before subcommand) with the non-hard-coded token the server was started with.

```bash
# Revisions — active pointer with CAS generation, list and single read:
cargo run -p loom-cli -- --admin-token $LOOM_ADMIN_TOKEN --output human admin revision list
cargo run -p loom-cli -- --admin-token $LOOM_ADMIN_TOKEN --output human admin revision get --revision-id loom-server
cargo run -p loom-cli -- --admin-token $LOOM_ADMIN_TOKEN --output human admin revision activate --revision-id loom-server --expected-generation 0  # CAS-gated

# Sessions — lifecycle Started/Committed/NoChange/Rejected/Failed/Blocked with safe provenance projection:
cargo run -p loom-cli -- --admin-token $LOOM_ADMIN_TOKEN --output human admin session get --session-id 00000000-0000-0000-0000-000000000050
cargo run -p loom-cli -- --admin-token $LOOM_ADMIN_TOKEN --output human admin session for-event --timeline $TIMELINE --event-id 00000000-0000-0000-0000-000000000020

# Provenance links Event → producing Session → Runtime Revision/implementation/read/call/entropy evidence:
cargo run -p loom-cli -- --output human history event --timeline $TIMELINE --event-id 00000000-0000-0000-0000-000000000020  # shows producing session id when linked
```

Every successful `ExecutionSession` was pinned to `TimelineTarget` + `TimelineVersion` + `World Runtime Binding` + `Runtime Revision` + exact compatible Capability implementations (the `Execution Assembly`) at session start. Stale cognition / fenced-out resolver results cannot commit; a CAS loser produces a `Discarded` observation retained in provenance.

### 3.9 Deterministic Agency Wake — supported via neutral deterministic fixture; default server composition still uses `UnavailableCognitiveExecutor`

The neutral V0 fixture provides a deterministic `CognitiveExecutor` (`deterministic.fake` via `crates/loom-agency/src/testing.rs:DeterministicCognitiveExecutor`) without vendor credentials. It is exercised through public `AdminService`/`Runtime` APIs in `tests/loom-composition/neutral_v0_workflows.rs::neutral_v0_agency_deterministic_without_vendor_credentials` and the CLI workflows `examples/neutral-v0/workflows/agency.sh`. The default `loom-server` composition still defaults to `UnavailableCognitiveExecutor` (`apps/loom-server/src/application.rs:411-420`) unless `with_cognitive_executor` is called by a future adapter — in the default server a scheduled Wake remains `TimelineBlockedOnMissingImplementation` until such wiring exists (use `admin timeline missing-implementation --work-id` to observe).

Supported deterministic example (via Runtime/composition tests and `loom-cli` against a fixture-wired Runtime):

```bash
# Schedule an explicit Agency Wake (Scheduler-managed durable Work with Agency target):
# Requires --work-id (mandatory for CLI) and a Runtime wired with the deterministic executor.
export LOOM_ADMIN_TOKEN=...  # must match server
cargo run -p loom-cli -- --admin-token $LOOM_ADMIN_TOKEN --output human admin agency schedule-wake \
  --world $WORLD --timeline $TIMELINE --work-id 00000000-0000-0000-0000-000000000060 --agent 00000000-0000-0000-0000-000000000021 --payload '{"trigger":"quickstart"}' --cognition deterministic.fake

# In the default server composition without that wiring, the Wake blocks:
cargo run -p loom-cli -- --admin-token $LOOM_ADMIN_TOKEN --output human admin timeline missing-implementation --world $WORLD --timeline $TIMELINE --work-id 00000000-0000-0000-0000-000000000060
cargo run -p loom-cli -- --admin-token $LOOM_ADMIN_TOKEN --output human admin session get --session-id <wake-session-id>
# See the deterministic fixture walk:
#   LOOM_CLI="cargo run -q -p loom-cli --" examples/neutral-v0/workflows/agency.sh $WORLD $TIMELINE
```

- `AgentWorldView` is constructed through Runtime mediation, never by direct Storage access; its visibility subset is Binding-checked, and its `ContextBudget` is enforced before cognition.
- `Decision::Act(ActionInvocation)` re-enters normal `Action → Resolution → ValidatedResolution → Logical Commit` authority; semantic rejection of the Act completes the same Wake as `NoChange` (no second attempt replaces the observed result; reconsideration is a new Wake — Amendment 0003 §3).
- Default policy after CAS loss is `Resample` (re-invoke cognition with fresh pinned version, 2× cost); `ReuseDeterministic` (1×) is explicit, provenance-visible and revalidated against the fresh coordinate. See `docs/operator-guide.md` §Agent visibility/CAS and `docs/capacity-envelope.md` for measured cost.

Real vendor LLM integration similarly remains non-blocking / deferred and must arrive as a reviewed provider adapter.

### 3.10 Restart and resume

```bash
# Restart is durable — all truth is in PostgreSQL + blob store:
docker compose restart loom-server
# Or native: stop loom-server (Ctrl-C / SIGTERM) then run it again with the same LOOM_DATABASE_URL/LOOM_DATA_DIR
# and the same Scheduler target and Admin token if you need those features.

# Verify after restart: history, feed, and scheduler all resume from committed position:
cargo run -p loom-cli -- --output human history events --world $WORLD --timeline $TIMELINE
cargo run -p loom-cli -- --output human feed subscribe --world $WORLD --timeline $TIMELINE --after 2 --limit 100
cargo run -p loom-cli -- --output human timeline inspect --world $WORLD --timeline $TIMELINE

# Expired leases are reclaimable; stale fences cannot retry/complete/terminalize.
# Use the exact required flags (global --admin-token before subcommand, per-command required --work-id/--expected-head-seq/--expected-state-rev):
cargo run -p loom-cli -- --admin-token $LOOM_ADMIN_TOKEN --output human admin timeline missing-implementation --world $WORLD --timeline $TIMELINE --work-id 00000000-0000-0000-0000-000000000070
cargo run -p loom-cli -- --admin-token $LOOM_ADMIN_TOKEN --output human admin work terminalize --world $WORLD --timeline $TIMELINE --work-id 00000000-0000-0000-0000-000000000070 --expected-head-seq 2 --expected-state-rev 2 --terminal-state dead
```

The worker helper checks the shutdown signal before each `drive_timeline` step; an active step is allowed to finish, so graceful stop does not revoke a live claim mid-commit. Process death after claim leaves the Work `Pending` with an operational lease; after lease expiry a later worker reclaims it with a newer fence. No in-process restart marker or Runtime-global mutex is required.

## 4. No-secret local examples

- Copy `.env.example` → `.env`; the committed defaults run locally with `POSTGRES_USER=loom`, `POSTGRES_PASSWORD=loom` (local-test-only).
- Replace `POSTGRES_PASSWORD` outside development; never commit provider/LLM credentials.
- `LOOM_ADMIN_TOKEN` and `LOOM_SCHEDULER_WORLD_ID`/`LOOM_SCHEDULER_TIMELINE_ID` must be supplied without hard-coded secrets via environment or `cargo run -p loom-cli -- --admin-token ...` and `.env` edits when those features are needed (see §2.1, §3.5, §3.8).
- Example `WorldTemplateDescriptor` and `IngressEnvelope` JSON are submitted through the CLI/API — never through direct SQL fixture mutation (`loom-storage` owns migrations/SQL exclusively).

## 5. Validated commands checklist

Every command above is a syntactically valid public CLI invocation verified by a parser sweep (`cargo run -p loom-cli -- <subcommand> --help` for each subcommand and `cargo run -p loom-cli -- --output human --help` for globals) and by `serde_json` deserialization for every JSON payload (WorldTemplateDescriptor, IngressEnvelope with `invocation.action`, SubscriptionRequest). The full sweep is recorded in the task evidence.

- Server: `cargo run -p loom-server` / `docker compose up` → `SystemClock` + `PgStorage` + `loom-boundary` → `Runtime::drive_timeline` via bounded `SchedulerWorker` **only when** `LOOM_SCHEDULER_WORLD_ID`/`LOOM_SCHEDULER_TIMELINE_ID` are configured (§3.5).
- Client: `loom-client` (`crates/loom-client`) — HTTP/JSON + SSE over `loom-api`.
- CLI: `cargo run -p loom-cli -- --help` plus all subcommand helps (listed in `apps/loom-cli/src/lib.rs`); `cargo test -p loom-cli --all-features` (deterministic JSON/cursors, `ApiErrorCode` exit codes 10–16, feed resume/fork/provenance/Admin workflows via `loom-boundary` + `InMemoryStore`). Global flags are `--output/--server/--admin-token` **before** subcommand.
- Persistence: `bash tools/postgres-test.sh up` then `cargo test --workspace --all-features` (or `bash tools/test.sh --workspace --all-features` which starts/uses the `loom_control` service at `postgresql://loom:loom@127.0.0.1:15432/loom_control` if `LOOM_TEST_POSTGRES_URL` is unset).

For full operator/developer deep-dives and measured capacity evidence, continue to `docs/operator-guide.md`, `docs/developer-guide.md` and `docs/capacity-envelope.md`.
