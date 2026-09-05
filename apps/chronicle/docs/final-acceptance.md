# C1-T17 final production acceptance

C1-T17 is the serial closeout gate for Chronicle C1. It is intentionally not a feature task: the gate independently proves the complete existing product/data-production path on the supported real deployment.

## What counts

The final evidence must come from a **Debian host**, `compose.chronicle.yaml`, PostgreSQL 18, the real Rust web front + Python read sidecar + durable worker, a previously unprocessed complete UTF-8 historical text, and a real external Responses-compatible model provider. T13–T16 model-boundary fixture runs remain useful regression evidence but cannot satisfy T17.

Production mode stays fail-closed. `apps/chronicle/acceptance/c1_t17_gate.py` refuses `CHRONICLE_MODEL_FIXTURE_PACK`, requires explicit extraction/presentation model names plus `CHRONICLE_MODEL_ENDPOINT`, and does not contain a fixture fallback.

## Prepare the Debian host

Use a clean checkout of the exact candidate commit. Configure `.env.chronicle` from `.env.chronicle.example` with at least:

```text
CHRONICLE_POSTGRES_PASSWORD=...
CHRONICLE_ADMIN_USER=admin
CHRONICLE_ADMIN_PASSWORD=...
CHRONICLE_MODEL_ENDPOINT=https://.../v1/responses
CHRONICLE_MODEL_API_KEY=...
CHRONICLE_EXTRACTION_MODEL=...
CHRONICLE_PRESENTATION_MODEL=...
```

Do not set `CHRONICLE_MODEL_FIXTURE_PACK`.

Choose two local files that represent the same logical complete document: `source-v1.txt`/`.md` is a previously unprocessed source; `source-v2.txt`/`.md` is a controlled changed revision. The second file must differ byte-for-byte from the first. Pick `--world-year` from the source's bounded historical period so the post-publication World check is meaningful.

## Run

From the clean repository root:

```bash
python3 apps/chronicle/acceptance/c1_t17_gate.py \
  --env-file .env.chronicle \
  --source /path/to/source-v1.txt \
  --replacement /path/to/source-v2.txt \
  --title 'T17 controlled source title' \
  --world-year 208
```

The runner is operator-side orchestration only. Business actions go through the authenticated Studio HTTP API and public HTTP API; container lifecycle goes through the production Compose file. It never writes Chronicle PostgreSQL directly.

The runner performs these checks in one auditable flow:

1. proves a clean exact commit, Debian/Linux, Docker/Compose, live-provider configuration and fixture exclusion;
2. starts the production Compose stack including the worker and records service state;
3. records the pre-ingestion Historical Moment for the selected year;
4. authenticates to Studio, creates a Document and uploads immutable revision 1, verifying the API SHA-256 against local bytes;
5. queues a real ingestion job;
6. stops the normal worker, uses the worker's existing fault-injection CLI to fail `prepare` once on the real revision, observes `failed`, calls the real Studio `/retry` API, and restarts the worker;
7. when possible, kills the production worker while the job is running, waits beyond the gate lease window and starts a fresh worker so PostgreSQL lease/checkpoint takeover is exercised; if a small document advances too quickly, the manifest records that the forced-kill window was missed rather than inventing restart evidence;
8. if real cross-source ambiguity creates ReviewItems, resolves them through the authenticated Studio Review API with a conservative non-merging decision (`uncertain`/`related_occurrence` where legal), then calls `/resume`;
9. waits for canonical publication and Reader Presentation to complete;
10. uploads changed revision 2, requires `revision_no=2` plus `supersedes_revision_id=revision1`, and proves revision 1 bytes are still retrievable exactly;
11. requires the canonical catalog to change, then runs the committed real-Chromium World browser smoke for World -> Event -> Entity -> evidence;
12. writes a secret-free evidence manifest and Compose/worker/browser logs under `apps/chronicle/.artifacts/c1-t17/` by default.

## Evidence handling

`manifest.json` is the primary evidence record. It includes the candidate commit, host fingerprint, Docker versions, non-secret provider configuration, local/source revision hashes, document/revision IDs, job progress, review decisions, before/after World snapshot, supersession proof and browser-smoke result.

The runner deliberately does **not** write admin passwords, database passwords or provider API keys. The provider API key is recorded only as `api_key_present: true|false`; endpoint query/fragment information is discarded.

Attach or archive the evidence directory for Issue #506. Do not commit credentials or the operator's source files.

## Interpreting restart evidence

The retry proof is deterministic and mandatory: the first worker invocation must fail `prepare`, the job must reach `failed`, Studio `/retry` must be accepted, and normal processing must subsequently continue.

The forced restart/takeover check requires the job to still be `running` when the runner reaches its kill window. For a source/model combination that completes too quickly, `manifest.json` records `forced_kill: false`. In that case T17 is **not complete**: rerun with a sufficiently substantial complete text (or otherwise create a legitimate long-running live-provider window) until `forced_kill: true` and subsequent completion are evidenced. Do not weaken the gate.

## Completion protocol

A successful local script run is necessary but not sufficient to close C1-T17. The delivery PR must also have final exact-head Chronicle/Docker/repository CI. After merge, use the mandatory post-merge Task Ledger reconciliation, re-read canonical `main`, close #506, then reconcile and close C1 root #489. Until all of that is true, T17 remains `in_progress` and the C1 root remains open.
