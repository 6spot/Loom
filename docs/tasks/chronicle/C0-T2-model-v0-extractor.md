---
task: C0-T2
issue: 463
status: completed
depends_on:
  - C0-T1
created_at: 2026-08-31
started_at: 2026-08-31
completed_at: 2026-09-01
completion_pr: 459
merge_sha: 2e6dec7689bccfd4fc409a4a0486824d4bcb5791
---

# Chronicle model-v0 extractor

## Goal

Replace the fixture-specific extraction step with the first real model/config-driven extraction path while preserving the Chronicle v0.1 staged contract, schema validator, and human-gold evaluation harness.

The boundary under test is:

`raw text + document context + ingestion config + JSON Schema -> model provider -> staged bundle -> schema validation -> ID-independent gold evaluation`

## Scope

- retain `rules-v0` as the deterministic baseline;
- implement `ModelV0Extractor` behind a small provider protocol;
- provide a vendor-neutral command provider that receives the prompt on stdin and returns model text on stdout;
- provide replay of captured model responses for deterministic offline evaluation;
- construct the model prompt only from raw source, document context, ingestion config, and Chronicle JSON Schema;
- keep `expected.yaml` structurally outside the model-input path and load it only after extraction;
- enforce a source-grounded/closed-book prompt: no background historical knowledge may be added;
- accept plain JSON and a single Markdown-fenced JSON object;
- normalize transport IDs/references and model extraction diagnostics without fabricating historical content;
- compare model output to human gold after dereferencing temporary IDs to stable entity/event labels;
- emit a machine-readable evaluation report;
- document commands and add offline unit tests.

## Non-goals

- permanent model/vendor selection;
- production API-key or secret management;
- canonical entity resolution / UUIDv7 publication;
- event deduplication or merge;
- PostgreSQL publishing;
- generalized reusable Loom ingestion capability;
- traditional-calendar month/day conversion without verified conversion data.

## Acceptance

- [x] `model-v0` extractor is implemented behind a provider protocol.
- [x] Command provider invokes an external model command without `shell=True` and passes the complete prompt via stdin.
- [x] Replay provider supports deterministic evaluation of captured model output.
- [x] Prompt contains raw source, document context, ingestion policy, and JSON Schema and contains no gold input.
- [x] Prompt explicitly forbids adding facts from prior historical knowledge.
- [x] Plain and Markdown-fenced JSON model responses are parsed; malformed/non-object responses fail clearly.
- [x] Transport temp IDs and internal refs are normalized without assigning canonical UUIDs.
- [x] Model extraction diagnostics use `extraction.method: model`; historical confidence is not fabricated.
- [x] Model gold comparison ignores temporary ID spelling/order by dereferencing entity/event/source references.
- [x] Machine-readable evaluation report includes counts, schema result, and gold mismatches.
- [x] Offline unit tests cover prompt isolation, provider invocation, response parsing, normalization, comparison, and evaluation reporting.
- [x] Full repository `unittest discover` run is verified after these commits are pulled into a checkout.
- [x] A real model provider has been invoked against the committed `sanguozhi-wudi-jianan-13` fixture and its evaluation report recorded.
- [x] Delivery PR / CI / merge reconciliation completed.

## Verification

- Local isolated `model_v0.py` tests: 6/6 passed on 2026-08-31.
- `python3 -m py_compile model_v0.py chronicle_cli.py` passed before repository write.
- No external model/API call was used for the unit tests.
- Real `gpt-5.6-luna` extraction against the committed fixture completed; its first exact comparator produced 73 mismatches and directly motivated Evaluator v2 rather than prompt tuning to gold wording.
- The same captured model output was later replayed through Evaluator v2 with zero hard failures.
- Full current Chronicle prototype suite on 2026-09-01: `Ran 50 tests` / `OK`.
- Repository CI has no Chronicle/Python lane; no Chronicle GitHub CI pass is claimed.
- Delivery PR #459 merged to `main` as `2e6dec7689bccfd4fc409a4a0486824d4bcb5791`.

## Progress log

- 2026-08-31 — Issue #463 created after C0-T1 rules-v0 passed in the user's repository checkout.
- 2026-08-31 — Implemented provider-neutral model-v0 core, closed-book prompt, response parsing, transport normalization, ID-independent semantic evaluation, unified CLI, evaluation report, and six offline tests.
- 2026-08-31 — Invoked the real Luna provider against the committed fixture; the output was schema-valid and became the fixed Run #1 input for Evaluator v2 work.
- 2026-09-01 — Reconciled as completed after the complete 50-test suite passed and PR #459 merged.
