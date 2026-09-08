# C1-T17 final production acceptance

C1-T17 is the serial closeout gate for Chronicle C1. It is not a feature task: it independently proves the complete existing Book-to-Chronicle -> Historical World path on the supported real deployment.

C1-T17 is completed; its acceptance decision, delivery and reconciliation are archived in the [task record](../../../docs/tasks/chronicle/C1-T17-final-acceptance-gate.md). This guide retains the explicit operator procedure for future requested acceptance runs. The temporary T17 live-model Actions workflow has been retired.

## What counts

The final evidence must come from a **clean Debian host**, `compose.chronicle.yaml`, PostgreSQL 18, the real Rust web front + Python read sidecar + durable worker, a previously unprocessed complete UTF-8 historical text, and a real external Responses-compatible model provider. T13–T16 model-boundary fixture runs remain useful regression evidence but cannot satisfy T17.

Production mode stays fail-closed. `apps/chronicle/acceptance/c1_t17_gate.py` refuses `CHRONICLE_MODEL_FIXTURE_PACK`, requires explicit extraction/presentation model names plus `CHRONICLE_MODEL_ENDPOINT`, rejects endpoint-embedded credentials, and contains no fixture fallback.

## Operator-only prerequisites

Normal Chronicle deployment still needs only Git + Docker. The **final acceptance operator** additionally needs:

- Python 3 on the Debian host to run the orchestration script;
- Chrome/Chromium on the host for the real headless browser checks;
- access to the configured external model provider;
- an interactive terminal if the live source creates blocking resolution ReviewItems, because those decisions must be made by a human in Studio.

Use a dedicated fresh `CHRONICLE_DATA_DIR` for the final gate. The runner rejects a revision-1 source SHA-256 already present in Chronicle so a failed/debug run cannot be silently presented as a first ingestion. If you need to rehearse, use a disposable data directory and perform the final evidence run from a clean fresh directory.

Before an operator-requested fresh run, require Chronicle, Chronicle Docker
and applicable repository CI to pass on the frozen candidate SHA. Run the
explicit [live-provider preflights](reader-presentation.md#offline-pipeline)
for extraction and Claim-bound Entity/Event presentation from the same checkout
with the configured provider and an isolated PostgreSQL test database. A code
change requires these checks on the new candidate and fresh data/evidence/log
paths; failed runs remain failure evidence. Ordinary development does not
automatically repeat the completed T17 acceptance run.

## Prepare configuration

Use a clean checkout of the exact candidate commit and configure `.env.chronicle` from `.env.chronicle.example` with at least:

```text
CHRONICLE_POSTGRES_PASSWORD=...
CHRONICLE_ADMIN_USER=admin
CHRONICLE_ADMIN_PASSWORD=...
CHRONICLE_MODEL_ENDPOINT=https://.../v1/responses
CHRONICLE_MODEL_API_KEY=...        # when required by the provider
CHRONICLE_EXTRACTION_MODEL=...
CHRONICLE_PRESENTATION_MODEL=...
```

Do not set `CHRONICLE_MODEL_FIXTURE_PACK`.

Choose two local files for the same logical complete document. `source-v1.txt`/`.md` must be a previously unprocessed source. `source-v2.txt`/`.md` is a controlled changed revision and must differ byte-for-byte from revision 1. Pick `--world-year` from a period actually represented by the source so the post-publication World check can identify a newly published or newly enriched Event.

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

The runner is orchestration-only. Product mutations go through the authenticated Studio HTTP API; public inspection goes through the public HTTP API; container lifecycle goes through the production Compose file. It never writes Chronicle PostgreSQL directly. The existing `apps/chronicle/corpus/metrics.py` is executed inside the worker container only for read-only before/after operational evidence.

## What the runner proves

1. clean exact candidate commit, Debian/Linux, Docker Engine/Compose versions and PostgreSQL 18 server version;
2. live-provider configuration with fixture exclusion, while recording no passwords/API keys;
3. Studio auth fail-closed without credentials and succeeds with the configured single admin;
4. the retained C0 two-source browser regression remains available on the real deployment;
5. source SHA-256 was not already present, then Studio creates a Document and uploads immutable revision 1 with exact hash verification;
6. Studio queues a real ingestion Job;
7. deterministic **retry proof** on that real source: stop the normal worker, invoke the existing worker fault-injection CLI to fail `prepare` once, observe `failed`, call the real Studio `/retry` API, then restart production worker-A;
8. deterministic **restart/takeover proof**: observe worker-A owning the durable lease, kill it with `SIGKILL`, wait beyond the 15-second gate lease, recreate the service as worker-B, and require the PostgreSQL job attempt to increment before processing can complete;
9. if genuine cross-source ambiguity produces resolution ReviewItems, pause and require the operator to resolve them in `/studio/review`; the runner refuses non-interactive auto-decisions, re-reads the resulting decisions, calls `/resume`, and continues;
10. canonical publication and Claim-supported zh-CN Reader Presentation complete;
11. upload changed revision 2, require `revision_no=2` and `supersedes_revision_id=revision1`, then retrieve revision 1 exact bytes after replacement;
12. collect before/after corpus density + Coverage and require the published `catalog.latest_catalog_sha256` from Historical Moment to change; missing or invalid hashes fail immediately, including before ingestion;
13. identify a newly published **or newly enriched** Event for the selected year whose direct evidence is an exact substring of revision 1 and whose Reader Presentation support also traces to a revision-1 Claim; record whether the canonical Event ID was reused;
14. run real Chromium through Timeline + Search + World -> that Event -> canonical Entity/Place -> exact evidence while preserving the selected historical-time context.

The Event sample must bind both direct evidence and Reader support to the
uploaded revision's `c1rev-<id>` bundle and the same direct Claim ref. Matching
quote text alone is insufficient: an older source can contain the same words.
The manifest records the evidence revision, bundle, Claim ref and text hash.

After the script succeeds, perform the
[Reader grounding/readability inspection](reader-presentation.md#t12-manual-groundingreadability-inspection)
on the generated presentations. Archive the public projections and a separate
`manual-reader-review.json` with the inspected IDs/hashes and content verdict.
The script checks provenance references and navigation; its PASS does not prove
that a paraphrase preserves who acted, who received an action, or whether a
source reported a rumor. A material content error leaves final T17 acceptance
failed even when the original script log, exit code and manifest say PASS.
Preserve those original observations and record the content failure separately.

## Review behavior

The final gate is deliberately not an identity oracle. If the job enters `needs_review`, the script prints the Studio Review URL and pauses. You decide `same_entity`, `same_occurrence`, `uncertain`, `related_occurrence`, etc. from the actual source evidence in Studio. The script then verifies no ReviewItems for that job remain open and records the resulting decision metadata. It never chooses a semantic identity decision automatically.

If `needs_review` is caused by something other than the supported resolution review workflow, the gate fails rather than weakening acceptance.

## Waiting for durable progress

The waits before and after resolution review each have a six-hour absolute
limit and a 30-minute limit without durable progress. A complete book can
produce many sequential Reader targets, so the idle limit is renewed only by
newly completed stages/chunks or new committed output IDs. Heartbeats,
timestamps, repeated outputs and model retries do not renew it. Progress never
substitutes for the required completed job, and an unexpected terminal state
still fails immediately.

`job-progress.jsonl` and the terminal report stage/chunk completion, committed
Reader counts and idle time at least every 30 seconds while polling succeeds.
This distinguishes a long productive stage from a stalled request; it does
not claim to fix provider latency or change production model timeouts. A run
that already timed out retains its original failure verdict.

## Evidence directory

By default evidence is written to:

```text
apps/chronicle/.artifacts/c1-t17/
```

`manifest.json` is the primary record. It includes:

- exact candidate commit and clean-checkout assertion;
- Debian host fingerprint, Docker/Compose and PostgreSQL versions;
- non-secret provider endpoint/model names and only `api_key_present: true|false`;
- local source hashes and persisted revision metadata;
- Studio authentication result;
- retry failure detail, worker-A lease, worker-B takeover attempt and completed Job/stage/chunk/run projection;
- human review decisions when present;
- before/after corpus density and Historical Moment/Coverage summaries;
- canonical ID reuse/new-ID sample, exact evidence hash and Claim-supported Reader Presentation sample;
- revision-2 supersession + revision-1 exact-content proof;
- C0 regression and T17 World/Timeline/Search browser-smoke hashes.

Compose status/images and worker/browser logs are saved beside the manifest. The runner does **not** write admin/database passwords, provider API keys, model prompts or raw model responses.

`manifest.partial.json` is checkpointed after the baseline, job creation,
takeover, human review, job completion, source replacement and final public
observations. `world-before.json` and `world-after.json` retain the actual public
Historical Moment responses. These partial records preserve already observed
evidence if a later check fails; only a successful full gate writes
`manifest.json`, and partial evidence never counts as PASS.

Attach/archive this directory for Issue #506. Do not commit credentials or the operator's source files.

## Failure policy

A gate failure is evidence, not permission to weaken the check. In particular:

- provider unavailable/invalid output remains fail-closed;
- if worker-A finishes before the forced-kill lease is observed, rerun with a sufficiently substantial source/model window;
- if worker-B does not increment the durable attempt after lease expiry, restart/resume is not proven;
- if the selected World year has no newly published/enriched Event grounded in revision 1, choose the correct bounded year/source and rerun;
- if the resulting Reader Presentation is not Claim/source traceable, T17 fails;
- if a semantic/authority gap is discovered, stop and use the executable-task/Architecture Amendment process rather than patching new scope into T17.

## Completion protocol

C1-T17 delivery PR #535 and reconciliation PR #542 are complete; their historical workflow results remain part of the archived acceptance evidence. For a later executable acceptance task, record its exact-candidate CI, explicit live-provider preflights, real-machine run and separate content inspection, then follow the repository [task-completion procedure](../../../docs/development/task-completion.md) for delivery, default-branch reconciliation and Issue closure. The completed T17 workflow is not a standing merge prerequisite for future development.
