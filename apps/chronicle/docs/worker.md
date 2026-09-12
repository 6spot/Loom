# Chronicle durable ingestion worker (C1-T4, C2-R1-T13 chapter pipeline)

Standalone, restart-safe execution for long-running book ingestion. The
worker is a plain Python process
(`apps/chronicle/worker/ingestion_worker.py`); PostgreSQL 18 is the only
coordinator. There is deliberately no Redis, Celery, RabbitMQ, Kafka, or
any other queue service in this envelope (see "Why no queue service").

## Run

```bash
export CHRONICLE_DATABASE_URL=postgresql://chronicle:...@postgres:5432/chronicle
python3 apps/chronicle/worker/ingestion_worker.py \
  --worker-id worker-01 --lease-seconds 300 --poll-interval 5
```

Flags: `--database-url` (else `CHRONICLE_DATABASE_URL`), `--worker-id`
(default `worker-<host>-<pid>-<rand>`), `--lease-seconds` (default 300),
`--poll-interval` (default 5s), `--max-jobs` (stop after N jobs; default
runs until SIGTERM/SIGINT), `--source-dir` (else `CHRONICLE_SOURCE_DIR`;
when set, `structure`/`segment` run the real C1-T5 segmentation over
stored revision bytes — see `segmentation.md` — and every source failure
fails the job instead of falling back to fake checkpoints),
`--fail-stage STAGE[:COUNT]` (fault-injection demos only; never set in
production).

Compose ships an opt-in worker service (profile `worker`, not started by
the default stack):

```bash
docker compose -f compose.chronicle.yaml --profile worker up -d chronicle-worker
```

### Production extraction / presentation model provider

C1-T13 wires the tested `chunk_model` and `presentation_model` hooks into the
real worker process through a Responses-style HTTP boundary. Configure
`CHRONICLE_MODEL_ENDPOINT` plus either or both model names:

```bash
export CHRONICLE_MODEL_ENDPOINT=https://api.openai.com/v1/responses
export CHRONICLE_MODEL_API_KEY=...
export CHRONICLE_EXTRACTION_MODEL=...
export CHRONICLE_PRESENTATION_MODEL=...
```

The endpoint is vendor-neutral at the Chronicle boundary: OpenAI can be used
directly, while Luna or a local service can sit behind a compatible gateway.
Extraction and Reader Presentation remain independent model selections. If
both names are empty, no network model provider is constructed and the prior
worker behavior is unchanged. If a model name is configured without a valid
HTTP(S) endpoint, startup fails closed. Credentials are accepted only through
`CHRONICLE_MODEL_API_KEY`, never embedded in the endpoint URL. Provider errors
do not echo response bodies or API keys; the existing extraction/presentation
validators still own schema, evidence grounding, uncertainty and publication
authority.

Both live providers send strict Responses `text.format` constraints for their
own contracts: extraction uses the staged-bundle projection and presentation
uses the [Reader Presentation candidate shape](reader-presentation.md). The
presentation prompt supplies the exact canonical target; the output validator
still rejects a missing or mismatched target instead of filling it in.

### Joint natural-chapter pipeline (C2-R1-T13)

When a revision source (`--source-dir` / `CHRONICLE_SOURCE_DIR`) and a
joint chapter model are both configured, every content stage runs the
natural-chapter pipeline instead of the C1 chunk path; `prepare` keeps
the deterministic fake executor so the frozen 8-stage authority is
unchanged. Thin orchestration lives in
`apps/chronicle/worker/chapter_stage.py` (the sole wiring owner is
`ingestion_worker.py`):

- `structure` / `segment` persist the T03 plan with exactly one work
  chunk per natural chapter (absolute chapter coordinates, content
  hashes, request fingerprints in chunk checkpoints).
- `extract` runs one whole-chapter joint call plus at most one
  whole-chapter correction per chapter (T05/T06; never the old
  independent chunk prompt). The lease is renewed before and after
  each model wait while no DB transaction is ever held across a call;
  every durable write is lease-fenced. Accepting re-validates the
  exact request/candidate pair and the producing-run fingerprint; an
  accepted run whose checkpoint commit never landed is adopted from
  its complete stored request/response with zero new model calls.
  `candidate_version_for_model` selects the candidate generation a
  model produces: the live joint provider plans the 0.3 person-state
  contract (reading annotations plus `person_states`); the reading
  fixture plans 0.2 and the frozen first-round fixture stays 0.1.
  The planned request declares that version, so prompt, strict output
  format and acceptance validator always agree; a 0.3 candidate is
  accepted only through the T01 `person_state_contract`, and a 0.2
  candidate only through `reading_contract`, each keeping its
  program-resolved units/candidate keys.
- `assemble` requires every expected accepted chapter (T07; partial
  books fail closed) and records one revision bundle output. A 0.3
  bundle also persists its assembled `person_states` block and evidence
  manifests next to the source bundle, so resolve and publish consume
  exactly the accepted bytes.
- `resolve` freezes the mixed review plan (`chapter_pair` +
  `published_batch`, T08) as a job output; resume reuses that exact
  plan (never rebuilding or re-ranking it) and parks in
  `needs_review` while any candidate is open. After the identity
  reviews are terminal, a 0.3 job freezes one `chapter_state_evidence`
  package per chapter from the accepted artifacts, the assembled state
  evidence, the final Resolution hashes and the base catalog
  (`person_state_review`), records that plan as a job output and keeps
  parking until every state package is terminal. Zero candidates
  proceed unattended.
- `publish` runs `resolve_publish.publish_chapters` in one short
  transaction under the unified advisory lock: latest catalog by
  `publication_sequence` (never `imported_at`), lease re-verified
  under the lock, frozen plan re-validated exactly, terminal decision
  required for every candidate. The lease check is expiry-aware on the
  live clock (`clock_timestamp`, not transaction-start `now()`): it is
  re-asserted after the expensive catalog/assembly computation, after
  the reading compile, and again immediately before the commit, so a
  lease that expires mid-transaction (or is taken over) fails closed
  with `LeaseLost` and rolls back every write instead of committing on
  a stale lease. For a reading book (0.2 or 0.3) the caller's T03
  `chapter_plan` is strictly bound to the persisted T03/assembled record:
  the canonical T03 `plan_sha256` is recomputed over the complete plan
  (version, revision binding and every chapter's blocks/`content_sha256`/
  `required_block_ids`) and must match both the plan's own declared hash
  and the persisted hash, the revision binding and plan geometry are
  compared, and the re-assembled bundle must equal the persisted
  `assembled-source-bundle` hash before it also compiles the T04
  projection and persists the whole T05 reading index (stream, units,
  time groups, event occurrences) **inside the
  same transaction**, after the catalog and every chapter publication and
  before the publish checkpoint. A 0.3 book first re-verifies every frozen
  state binding after the final resolutions are derived: the assembled
  ``person_states`` hash must equal the plan's ``assembled_hash``, the
  complete evidence-manifest digest is computed before
  ``person_state_plan_fingerprint`` and is a first-class fingerprint input
  (``evidence_manifests_sha256``, recomputed by
  ``validate_person_state_review_plan`` and therefore binding every review and
  assessment to the exact manifests) and must match the persisted manifests,
  every manifest must
  still carry the accepted ``artifact_sha256``/``source_sha256``/
  ``normalized_sha256`` (and agree with the accepted artifact's own
  ``person_states_sha256``), the manifests must still map every frozen
  candidate to its ``revision_ref``, the accepted-artifact and Resolution
  hashes and the base catalog must match the plan, and every candidate/fact/
  order/continuity/disagreement/unit-phase reference must stay inside the
  assembled phase set (a wrong phase never compiles with a fallback label).
  The manifests are additionally re-derived by a fresh assembly from the
  accepted artifacts under the bound chapter plan before any public write.
  Only then, in the
  same transaction, it persists the reviewed T06 assessment artifact,
  compiles the T04 person-state projection once per reading unit with that
  unit's frozen phase binding, and writes the immutable T05 state
  manifest/index plus the catalog disagreement index; a missing plan, an open
  state review, an unbound unit, an oversized item, a drifted state or
  evidence-manifest hash or a
  wrong-phase association fails closed with no public row. The compiled
  stream identity is derived
  deterministically from the revision, so recompiling and replaying
  the same revision reuses the exact stream/units/state-manifest without a
  second model call. Catalog, every chapter publication, canonical maps,
  catalog output, reading index, person-state index and publish
  checkpoint/completed
  commit together; any fault rolls back all public content (no
  partial reading or person-state index). A moved baseline raises
  `publication_plan_stale`: the frozen plan and its evidence are kept,
  nothing is auto-passed or rebuilt (a follow-up job must replan). All
  catalog writers (chapter publish, legacy publish, dataset import)
  take the same lock.
- `present` only verifies the published complete translation blocks;
  it never re-translates and never substitutes a blurb for the full
  text. A 0.2/0.3 book additionally verifies that exactly one reading
  stream binds this job's chapter publications with at least one
  unit/group. A 0.3 book also verifies that exactly one person-state
  manifest binds that same stream/publication snapshot, cites at least
  one reviewed assessment and carries its bounded index, so `present`
  never passes while a partial reading or person-state index is public.

### Production chapter schema / provider / limits entry

`production_worker.py` selects the formal chapter entry
(`chapter_configs`): `ChapterLimits` from the documented
`CHRONICLE_CHAPTER_*` overrides plus the provider from
`CHRONICLE_CHAPTER_MODEL` + `CHRONICLE_MODEL_ENDPOINT`
(`CHRONICLE_MODEL_API_KEY` for credentials), or the explicit
`CHRONICLE_CHAPTER_FIXTURE_PACK` test injection. A real source
without a chapter model fails closed; the old fake executor is never
an implicit fallback for new chapters.

```bash
export CHRONICLE_MODEL_ENDPOINT=https://api.openai.com/v1/responses
export CHRONICLE_CHAPTER_MODEL=...
python3 apps/chronicle/worker/production_worker.py \
  --worker-id worker-01 --source-dir /data/chronicle-sources
```

A joint chapter model without a revision source fails the job before
any stage runs (no silent fake completion). A production entry
pointed at a source directory without any model refuses to start at
all; the composable library runner stays available for explicit test
injection (the pinned C1 segmentation/extraction tests rely on that),
while a real source without models keeps the explicit extract failure
instead of falling back.

### Reviewed multi-source historical narrative

Set `CHRONICLE_NARRATIVE_MODEL` alongside the chapter model, using the same
`CHRONICLE_MODEL_ENDPOINT`, API key and timeout. This enables an explicit
Studio operation; importing another chapter does not automatically regenerate
the public history. Source files must remain available through
`CHRONICLE_SOURCE_DIR` for complete, hash-verified chapter context.

In Studio → imports, select complete published chapters and create a historical
narrative job. It is an ordinary IngestionJob whose other stages are skipped.
Its `present` stage first creates a facts ReviewItem. Review the questions,
source relationships, phase boundaries and every conclusion, then approve and
continue. The worker creates prose using the accepted facts. Read and edit the
prose and selected navigation entries in the second review before continuing
to publication. The UI keeps save/next actions reachable on long pages and
allows conclusion splitting and phase/evidence editing.

The worker keeps model calls outside transactions and renews its lease on a
separate short connection. Each candidate permits up to three complete
generation/correction attempts; responses and diagnostics use the existing
ingestion output log. Accepted candidates are reused on resume. Publication
and completion commit together under the existing publication lock and an
expiry-aware lease check. A rejected draft cancels its job; cancellation
dismisses open narrative reviews without deleting their audit records.

The five-claim budget includes two normal review resumptions plus three
execution opportunities. After transient failures use the existing retry
operation. Changed source catalogs require a fresh selection and fresh review,
not automatic adoption of old decisions. The complete application contract,
capacity and versioned APIs are in [source-corroboration.md](source-corroboration.md).

Focused verification, with the canonical PG18 test environment:

```bash
python3 -m unittest discover -s apps/chronicle/corpus -p 'test_corroboration_cases.py' -v
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_narrative_contract.py' -v
python3 -m unittest discover -s apps/chronicle/worker -p 'test_narrative_pipeline_postgres.py' -v
```

These deterministic tests use explicit test models. Real historical content
also requires inspecting the generated facts and prose against the selected
complete sources, through both review gates; format or browser tests are not
a substitute for that content review.

## How durability works

1. **Claim.** `claim_job` takes one `queued` job — or one `running` job
   whose lease expired (crashed worker) or is missing (freshly
   retried/resumed) — with `SELECT ... FOR UPDATE SKIP LOCKED`. At most
   one active lease wins each job; independent jobs are claimed by
   different workers concurrently. The claim commits before execution
   starts.
2. **Execute.** The worker walks the frozen 8-stage pipeline
   (`prepare → structure → segment → extract → assemble → resolve →
   publish → present`). Stages/chunks already `completed` (or `skipped`)
   are never re-run: resume skips succeeded checkpoints by construction.
   The `extract` stage keeps the deterministic fake chunk executor
   unless a `chunk_model` provider is supplied with the C1-T5 revision
   source; the real C1-T6 path then runs context-aware contract-first
   extraction per chunk (bounded repair, fail closed, append-only run
   history — see `extraction.md`). The real path binds the canonical
   staged-bundle schema (`None` binds it; any non-canonical dict fails
   closed) and adopts
   an already-accepted run with zero new model calls when resume finds
   one whose status commit never landed.
3. **Short transactions, never across executor work.** Every database
   step runs in its own connection and commits exactly one transaction
   before the worker proceeds. Executor code runs with no transaction
   open, so a slow or hung stage holds no row lock: Studio cancellation
   never blocks on worker activity, and an expired lease row is never
   locked away from a reclaiming worker's `SKIP LOCKED` claim. Each
   committed step is immediately visible to other connections and
   survives a crash at any point.
4. **Lease fencing.** Every worker mutation (`advance_stage_fenced`,
   `set_chunk_status_fenced`, `record_chunk_run_fenced`,
   `set_job_status_fenced`, checkpoint/output writes, including the C1-T5
   `write_chunk_checkpoint_fenced`) predicates on the
   job lease inside the same transaction and raises `LeaseLost` for any
   worker that no longer holds it. Heartbeats are strict: losing the
   lease to a takeover (or to cancellation, which clears the lease)
   halts the stale worker with a `lease_lost` outcome instead of writing
   further state or evidence.
5. **Finish.** After all stages, the worker records one deterministic
   output and moves the job to `completed` (lease cleared). Faults park
   the job in `failed` (bounded Studio retry) or `needs_review` (chunk
   attempts exhausted; a `chunk_failure` review gate owns the job).
   Chunk attempts always append `ingestion_chunk_runs` rows with
   monotonically increasing `attempt`; retries never overwrite prior
   model/debug evidence.
6. **Shutdown.** SIGTERM/SIGINT finishes the current step, then stops.
   The job stays `running` under its lease, so the next live worker
   reclaims it after expiry. Shutdown never marks work failed and never
   invents checkpoints.

## Studio lifecycle operations

Authenticated Studio APIs (Rust `chronicle-server` → Python sidecar →
control-plane store; lifecycle authority stays in the server namespace
plus the control-plane state machine):

```text
POST /api/v1/studio/jobs                         {"revision_id": "..."}
GET  /api/v1/studio/jobs[?status=&limit=&offset=]
GET  /api/v1/studio/jobs/{job_id}
POST /api/v1/studio/jobs/{job_id}/retry    failed -> running (bounded)
POST /api/v1/studio/jobs/{job_id}/resume   needs_review -> running (gated)
POST /api/v1/studio/jobs/{job_id}/cancel   queued/running/needs_review -> cancelled
```

- `retry` refuses jobs that consumed `max_attempts` claim attempts, and
  resets only `failed` stages/chunks to `running`.
- `resume` refuses while any review item is still `open`, and resets only
  `needs_review` stages/chunks.
- `cancel` stops new work immediately; completed checkpoints stay intact.
  Cancelling an already-cancelled job is idempotent.
- Both `retry` and `resume` clear the stale lease so the next live worker
  can claim the job (a `running` job without a lease is claimable).
- Successful `resume` clears the old review error on the job and the resumed
  stages, so a running job no longer advertises a resolved review as a current
  blocker. Review decisions and append-only chunk-run history remain intact.

## Operational concurrency limits

| Bound | Value | Where |
| --- | --- | --- |
| Claim granularity | 1 job per claim, `SKIP LOCKED` | `claim_job` |
| Lease default | 300 s, owner-renewed | `--lease-seconds` |
| Idle poll | 5 s per worker, no thundering herd | `--poll-interval` |
| Job retries | `max_attempts` (default 3) claim attempts | `ingestion_jobs` |
| Chunk retries | `max_attempts` (default 3) per chunk | `ingestion_chunks` |
| Fake topology | 1 section, 2 chunks per job | `FAKE_CHUNKS_PER_JOB` |
| Real segmentation | versioned sections/chunks/context (C1-T5) | `segmentation.md` |
| Real extraction | versioned chunk candidates/history (C1-T6) | `extraction.md` |
| Chunk repair bound | `1 + max_repair_attempts` model calls per execution | `ExtractionConfig` |
| Job bodies | 64 KiB cap on Studio job requests | sidecar |

Scale guidance for the first envelope: run **one worker per 1–2 CPU** up
to a handful of workers on a single host against the Compose PostgreSQL
service. Claims are row-locked and short; heartbeats are one `UPDATE`
per stage/chunk. If claim latency or connection pressure ever becomes the
bottleneck (measured, not presumed), add read-replica-safe polling or
`LISTEN/NOTIFY` wakeups before reaching for external infrastructure.

## Why no queue service is required

- **Ordering/durability already hold.** Jobs, stages, chunks, runs, and
  reviews are rows with auditable transitions, not volatile messages.
  A broker would duplicate this ledger without adding guarantees.
- **Exactly-once execution is a lease, not a queue feature.**
  `FOR UPDATE SKIP LOCKED` plus expiring leases gives single-winner
  claiming and crash reclaim with zero moving parts beyond PostgreSQL,
  which the deployment already runs.
- **Backpressure is the jobs table.** `queued` depth and `failed` /
  `needs_review` counts are directly queryable (`GET /studio/jobs`);
  no separate dead-letter/monitoring system is needed at this scale.
- **Shutdown/restart is stateless.** Workers hold no local queues, so
  any worker may die at any point and the system converges by lease
  expiry alone.

Revisit only on measured evidence: sustained claim contention across
many workers, sub-second scheduling latency requirements, or a
multi-host topology where PostgreSQL connection limits bind first.

## Authority boundary

Application-owned product operations only (Amendment 0006): this worker
and the Studio job endpoints use `CHRONICLE_DATABASE_URL` and
`chronicle.*` tables. They never read or write Loom
Runtime/World/Timeline/Work/Binding state, never model ingestion as Loom
Scheduler Work, and never bypass the C0
staged/resolution/canonical historical-knowledge path.

## Verification

```bash
python3 -m unittest discover -s apps/chronicle/worker -p 'test_reading_pipeline_postgres.py' -v
python3 -m unittest discover -s apps/chronicle/worker -p 'test_chapter_pipeline_postgres.py' -v
python3 -m unittest discover -s apps/chronicle/worker -p 'test_*postgres.py' -v
python3 -m unittest discover -s apps/chronicle/worker -p 'test_production_worker_budget_unit.py' -v
python3 -m unittest discover -s apps/chronicle/read_api -p 'test_coverage*.py' -v
python3 -m unittest discover -s apps/chronicle/worker -p 'test_*.py' -v
python3 -m unittest discover -s apps/chronicle/read_api -p 'test_studio_jobs*.py' -v
python3 -m unittest discover -s apps/chronicle/persistence -p 'test_*.py'
cd apps/chronicle/server && cargo test --offline
```

The C1-T8 resolve/publish path is covered by
`persistence/test_resolve_publish_unit.py` (deterministic C0-reusing
core: candidates, decisions, publication boundaries) and
`worker/test_resolve_publish_postgres.py` (durable review-gated
resume plus unattended disjoint publication); see
`review-publication.md` for the contract.

The T06 reading publication path is covered by
`worker/test_reading_pipeline_postgres.py`: the full 0.2 chain publishes
one catalog, every complete chapter and one reading stream whose units
reassemble the published blocks; recompiling replays the same
stream/units without a model call; injected faults after the catalog,
after the chapters, inside the reading index and before the publish
checkpoint leave zero public rows; a chapter plan that drifts from the
persisted T03/assembled record (`normalized_sha256`, `source_sha256`,
`revision_id`, `plan_sha256`, chapter geometry, or an in-chapter covered
field such as a block `content_sha256`/range/`required_block_ids` even
when the supplied `plan_sha256` is left untouched or re-hashed) is
rejected with no public content; and a lease that expires while the
injected
assemble/reading compile runs fails closed with `LeaseLost` before the
first public write / stream write, rolling every row back. The
compile/store helpers are covered by
`persistence/test_reading_projection_unit.py` and
`persistence/test_reading_store_postgres.py`; the stream/event read APIs
belong to T07/T09.

The T08 person-state publication path is covered by
`worker/test_person_state_pipeline_postgres.py`: a fresh 0.3 revision
parks in `needs_review` on one `chapter_state_evidence` package per
chapter after identity Resolution, then resumes through publish/present
and exposes exactly one person-state manifest whose units bind the
reading stream and whose reviewed assessment is persisted in the same
transaction; replaying the same accepted artifacts/assessments/mapping
reuses the identical manifest and assessment without a model call; a
fault while writing the manifest leaves zero public rows and a clean
retry publishes the complete set. The same file also drives the full
0.3 → explicit composite job chain: source publication alone exposes no
history; the facts and prose review gates each block publication; after
both approvals the published history text, reviewed states and conclusion
evidence read back on one fixed `publication_version`, with the reviewed
source states present in the frozen composite context. Four independent
negative cases prove the publish boundary: mutating the persisted
assembled `person_states` fails closed with `state_drift`; mutating only a
persisted evidence manifest's `source_sha256` and rewriting the same row's
`report.evidence_manifests_sha256` still fails closed with `state_drift`
against the frozen plan digest; tampering the frozen plan's
`evidence_manifests_sha256` (while keeping the plan content key consistent)
is rejected by the plan fingerprint itself; and a frozen candidate phase
that is not in the assembled evidence fails closed with `wrong_phase`. Each
asserts every
public table (catalog, chapter, reading index, state
manifest/index/assessment/disagreement) stays empty. Unit tests in
`persistence/test_person_state_contract_unit.py` and
`persistence/test_person_state_review_unit.py` prove the
evidence-manifest digest is a fingerprint input. No-manifest 0.2
sources contribute an explicitly empty
`reviewed_person_states` list (regression in
`worker/test_narrative_pipeline_postgres.py`).
