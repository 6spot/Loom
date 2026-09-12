# Chronicle context-aware chunk extraction (C1-T6)

> 本页描述已实现的 C1 chunk 路径。本轮待实现的完整章联合翻译/抽取契约见 [chapter-production.md](chapter-production.md)；实施任务以该章节契约为目标，不把本文的小块处理规则扩大到新路径。

Deterministic, versioned extraction of one persisted book chunk into
schema-valid Entity/Event/Claim candidates with exact evidence and
replayable model-attempt provenance. Pure request/validation/history
logic lives in `apps/chronicle/persistence/extraction.py` (no database,
model, or network); the durable worker path lives in
`apps/chronicle/worker/ingestion_worker.py` (`extract` stage) on the
C1-T1 control-plane tables behind `CHRONICLE_DATABASE_URL`.

## What it produces

```text
persisted chunk (offsets, section, revision) + ContextState input
        │
        ▼
build_chunk_request → bounded prompt + request metadata
        │
        ▼
extract_chunk → initial attempt → validate → [bounded correction] → accepted | fail-closed
        │
        ▼
build_chunk_run → ChunkRun history (versions, request, attempts, candidate|error)
        │
        ▼
ingestion_chunk_runs rows (one per model attempt, append-only)
+ chunk checkpoint extraction layer (accepted candidate + producing run)
```

## Key contracts

- **C0 contract reused, not replaced.** Candidates satisfy the same
  staged Source/Entity/Event/Claim shape (`contract-v0.2`) and the same
  JSON Schema. No chunk assigns canonical identity: a record carrying
  `id` fails validation instead of being coerced.
- **Exact evidence per chunk.** Every `Claim.evidence.text` must be an
  exact substring of the *current chunk text*. Inherited context and
  boundary strings aid interpretation only and are never evidence.
  Chunk coordinates (offsets/hashes/revision) travel in the run
  envelope; the C0 `evidence.locator` shape is unchanged.
- **Inherited time without invented precision.** An `original_text`
  found in the chunk is explicit; one carried from ContextState must
  list `inherited_fields` verbatim. Normalized month/day always stay
  null; a normalized year is accepted only when document metadata
  supplies the exact verified mapping, otherwise it stays null too.
- **Replayable history.** Each attempt stores prompt, raw response,
  validation report, and candidate verbatim (within char bounds).
  `verify_history` re-parses and re-validates the stored pairs; any
  disagreement fails closed downstream.
- **Bounded repair, fail closed.** At most `1 + max_repair_attempts`
  model calls (default 1 repair, mirroring the C0 repair bound); a
  still-invalid candidate records the failure instead of manufacturing
  a valid-looking result.
- **ContextState is never authority.** It is stored beside the
  candidate under its own key, never merged into it, and every run and
  accepted checkpoint carries `authoritative: false`. Extraction
  confidence (`extraction.confidence`) stays separate from historical
  assessment (claims start `unassessed`).
- **Occurrence assertions remain Claim-backed.** Prompt `c1t6-prompt-v6`
  explicitly asks for source assertions about an occurrence, such as its
  result, as top-level Claims referring to the Event. A browsing Event's
  title and participants are not Claim evidence. This is initial extraction
  guidance, not a new mandatory-field validator or a second coverage pass:
  a Claim still requires exact source evidence and a faithful predicate;
  unsupported assertions stay omitted or produce `ontology_gap`.
- **Restart-safe.** Completed chunks are never re-run, so ordinary
  resume never duplicates a successful chunk. A chunk whose accepted
  run row committed but whose accepted layer/status did not (worker
  exit between those commits) is adopted from history with zero new
  model calls. Retries append new `ingestion_chunk_runs` rows; earlier
  attempts are never overwritten.
  The accepted-output layer records the producing run attempt, and the
  C1-T5 segmentation checkpoint is preserved alongside (merged, not
  replaced).
- **Schema bound by default.** The worker real-extract path binds the
  canonical staged-bundle schema (`require_canonical_schema`: `None`
  binds it, any non-canonical dict fails closed), so permissive
  dictionaries cannot accept malformed candidates. `schema=None` in
  the pure function skips only the schema layer for focused unit
  tests, never for production extraction. Schema evolution goes
  through contract versioning, never per-call dictionaries.

## Production model hook

The deployed worker keeps the deterministic fake `extract` path unless
a `chunk_model` provider (`complete(prompt) -> str` plus `name`) is
supplied alongside the C1-T5 `revision_source`. A model without a
revision source fails the job instead of extracting unknown bytes.
Optional `extraction_schema` (full JSON Schema dict) and
`allowed_predicates` tighten validation; `document_meta` supplies
document-level metadata such as a verified normalized year over the
database title.

## Fixture

`apps/chronicle/ingestion/fixtures/c1t6-inherited-jianan/` (`raw.txt`
plus `extraction.json`) segments into paragraph-aligned chunks where
only the opening chunk carries the explicit regnal year 建安十三年;
later chunks inherit it verbatim with the verified normalized year
208 and resolve 其/公-style references against inherited surfaces.
The unit suite (`persistence/test_extraction_unit.py`) and the
PostgreSQL extract suite (`worker/test_extraction_postgres.py`)
consume it.

## Whole-chapter joint translation/extraction (C2-R1-T05)

> 本节描述 C2-R1 完整章联合路径（Issue #555，Task C2-R1-T05）。权威契约见
> [chapter-production.md](chapter-production.md) §§3–4；本节只说明纯函数落点，
> 不复制规范。上文 C1 小块路径保持不变。

Deterministic, versioned joint translation/extraction of one complete
natural chapter into a `chronicle.chapter-candidate / 0.1` joint product
(full faithful translation plus the staged bundle, mentions, and
record_sources), validated by the T01 contract validator. Pure
prompt/execution logic lives in
`apps/chronicle/persistence/chapter_prompt.py` (`c2r1-chapter-prompt-v1`)
and `apps/chronicle/persistence/chapter_extraction.py`
(`c2r1-extraction-v1`): no database, model transport, network, or worker
changes. Transport retries belong to T06; the T13 worker owns run
identity, persistence, and atomic publication.

```text
program-owned chapter request (T03 build_chapter_request)
        │
        ▼
render_chapter_prompt → whole chapter + schema + source/plan metadata
        │
        ▼
extract_chapter → initial attempt → T01 validate → [one whole-chapter correction] → accepted artifact | typed failure
        │
        ▼
accepted chronicle.chapter-artifact / 0.1 (candidate, anchors, fingerprints, producing run) handed to T13
```

Key contracts:

- **Whole chapter in every call.** The initial prompt and the single
  correction prompt both carry all blocks, the required-block list, and
  the full normalized text verbatim, including the tail. A correction
  regenerates one complete chapter product from full context plus a
  bounded diagnostic list; failed segments are never translated alone
  and spliced back.
- **T01 validator reused, not duplicated.** Acceptance is
  `validate_chapter_candidate` plus `accept_chapter_candidate` only. No
  weaker parallel checks exist in this path.
- **One correction, then fail closed.** At most two model calls
  (initial + one correction). Missing model, oversized source/prompt/
  response, transport errors, and a second still-invalid product all
  return typed failures (`missing_model`, `source_over_limit`,
  `prompt_over_limit`, `response_over_limit_*`,
  `model_transport_error`, `validation_failed`); nothing is truncated
  and there is no chunk fallback. Transport failures are recorded, not
  retried here, so correction rounds stay distinguishable from provider
  transport retries.
- **Full audit trail.** Every attempt stores prompt, sizes/hashes, raw
  response, validation report, and candidate verbatim, plus the
  limits/model/schema/source/plan fingerprints. `verify_history`
  re-parses and re-validates stored pairs; disagreement fails closed.
- **Mechanical evidence only.** A passing validation report proves
  contract shape (coverage, reference closure, anchors, time precision,
  same-chapter alias discipline such as 曹操/操 sharing one temp_id
  while 公/王 stay contextual). It is never presented as
  content-accuracy evidence; real-corpus review belongs to T19.

Unit suite: `persistence/test_chapter_extraction_unit.py` (fake
`complete(prompt)->str` callable covering all branches).

## Whole-chapter joint translation/extraction + reading annotations (C2-R2-T03)

> 本节描述 C2-R2 的显式 0.2 联合路径（Issue #572，Task C2-R2-T03）；当前默认生产为下文的 0.3。
> 契约权威见 [continuous-reading.md](continuous-reading.md) §§2–3；本节只说明
> 生成/provider 落点，不复制规范。上文 C2-R1 的 0.1 小节保持不变。

An explicit 0.2 request emits `chronicle.chapter-candidate / 0.2` — the frozen 0.1
joint product (full translation + staged bundle + mentions + record_sources)
plus one `reading` block — in the *same* whole-chapter request. There is no
per-segment call and no read-time semantic annotation.

- **Version registration.** `persistence/chapter_contract.py` owns the
  candidate/artifact version registry, schema paths/IDs, and
  `candidate_schema_for(...)` / `artifact_schema_for(...)`. 0.1 stays
  frozen, 0.2 remains explicitly selectable, and 0.3 is the production
  default. The 0.2 validator is **not** reimplemented here.
- **One whole-chapter call + at most one whole-chapter correction.**
  `chapter_prompt.render_chapter_prompt` renders the 0.2 reading guide on
  top of the joint guide (main narrative vs. retrospective spans,
  translation quotes + occurrences, context entities and event roles,
  unknown/inherited time, original-calendar fidelity) and carries the full
  normalized text in both the initial and the correction prompt.
  `chapter_extraction.extract_chapter` dispatches acceptance by request
  version: 0.1 → `chapter_contract`, 0.2 → the T01
  `reading_contract.validate_reading_annotations` /
  `accept_reading_candidate`. A 0.2 request can never silently downgrade to
  0.1; an unregistered version fails closed as
  `unsupported_candidate_version` before any model call.
- **Consumer-side error categories.** A full-validation failure records
  `error.categories` (for example `reading_coverage`, `reading_spans`,
  `reading_time`, `reading_refs`, `reading_context`) so a missing unit, an
  overlapping span, or a wrong current-time basis is checkable without
  parsing the free-form message. Metadata errors reject the joint product
  instead of returning translation-only success.
- **Fingerprints/run history.** `fingerprints` records
  `candidate_schema` (`.../0.1` vs `.../0.2`), `prompt_version`
  (`c2r1-chapter-prompt-v11` vs `c2r2-chapter-prompt-v6`),
  `extraction_version` (`c2r2-extraction-v2` for 0.2),
  `correction_policy_version`, and — for 0.2 — `reading_schema` /
  `reading_limits`, so model/contract/limit versions stay distinguishable.
- **Provider/fixture parity.** `worker/extraction_model_schema.py` keeps the
  frozen 0.1 projection and adds `reading_chapter_candidate_model_schema()`
  with the required `reading` block; `chapter_candidate_text_format()`
  returns the current production format and
  `chapter_candidate_text_format_for("0.2")` selects the reading format.
  `model_provider.build_chapter_model(..., candidate_version="0.2")` keeps
  the 4 MiB response cap / explicit output-token budget and declares the
  same version to the worker. Environment wiring resolves the existing
  fixture name selector before building the provider, keeping the planned
  request and strict format on one version; ordinary live names default to
  production 0.3. The version metadata is local, not an extra provider field.
  `fixture_model.build_reading_chapter_candidate` /
  `models_from_reading_chapter_fixture_pack` emit the same 0.2 shape from
  one whole-chapter request.
- **Still worker-owned.** Model run identity, lease-fenced persistence, the
  atomic publish transaction, and the plan's `schema_versions` selection
  remain with the worker/publication task (T06); this task delivers the
  generation and provider layer only.

Unit suites: `persistence/test_reading_extraction_unit.py`,
`worker/test_reading_model_schema_unit.py`,
`worker/test_reading_provider_unit.py`; the 0.1 first-round regression
suites above stay in place.

### Correction integrity for 0.2 and 0.3

Both versions use the same bounded, whole-chapter correction path. The
correction task, diagnostics and previous complete candidate follow the
full source text. There is still at most one correction, returning one
complete joint candidate; no patch-only output, per-paragraph model call,
automatic splicing, or additional semantic retry is introduced.

`chapter_extraction` inspects the **full original validator report** before
selecting the repair scope. If the only failures concern known references,
anchors, aliases, reading annotations or person-state metadata, and the
translation has valid unique block IDs and non-empty text, the correction
must preserve every ordered `(block_id, text)` exactly. Source block links,
entity/event refs, spans and person-state annotations remain repairable; a
span may move to the block containing its literal quote. The prompt does
not simultaneously ask for prose expansion in this mode.

Schema, source-coverage/order, identity, capacity, duplicate/invalid block
IDs, parse failures and unknown error categories retain the ordinary full
chapter repair. This includes a missing tail or an overlong paragraph that
needs splitting, including when 0.3 nests those failures under `reading`.
Neither branch certifies semantic completeness: an initial summary can
still satisfy structural coverage and must be caught by content review.

The correction uses at most twenty diagnostics, each bounded to 280
characters, within 4,096 characters plus an omission summary when needed.
Distinct array indices remain distinct repair locations. A chapter-wide
anchor hint names a source block only for a unique match; repeated names
require passage-context disambiguation, never automatic selection of the
first occurrence. Full unabridged reports remain in attempt history. The
archived 2026-09-12 v4 failure's sixteen diagnostics all fit this envelope.

New runs bind `correction_policy_version=c2-chapter-correction-v1` in their
fingerprints. Each parsed correction records `correction_validation` with
the policy version, mode, pass/fail and differences. A prohibited rewrite
rejects the complete product with `error.categories.translation_preservation`,
even if candidate validation alone passes. Both original responses remain
unchanged in the history. `verify_history` recomputes the same scope and
comparison from those responses; it does not trust the stored decision.
Original `c2r2-extraction-v1` / `c2r3-extraction-v1` histories keep their
pre-policy interpretation, and unknown/missing current policy versions fail
replay. Extraction, policy and prompt generations must agree, including the
actual prompt header and recorded hashes/sizes. Replay also checks raw text
against the cached candidate, retains the initial evidence before correction,
and enforces the initial-plus-one-correction sequence and round count. Changing
a new run's version labels cannot opt it into the legacy rule. The 0.1 path
is unchanged.

Regression suite: `persistence/test_chapter_correction_unit.py`. It includes
the saved real v4 collapse, structurally valid but shortened corrections,
legitimate reference/span repairs, structural prose repairs and history
tampering. These offline checks do not replace a fresh real-provider run
and independent source-to-translation review. The Chronicle static CI lane
runs the correction, extraction and worker/provider unit suites.

### Whole-chapter interpretation guidance

The 0.2 prompt v6 and 0.3 prompt v4 add a shared fidelity guide after the
complete source for initial generation and full-chapter structural repair.
It asks the model to distinguish narrators and quoted speakers, resolve
omitted subjects from the full chapter, preserve historical word meanings
and embedded notes, and retain source-backed assertions as Claims rather
than treating Event titles as evidence. Supported source-calendar fields
recovered from another phrase must be declared as inherited, including
after a date-quote correction.

This is guidance within the existing joint generation call, not a new
semantic validator, extra model review, Claim-count floor, or external
historical source. It contains no corpus-specific names or expected answers.
Metadata-only correction omits the prose fidelity guide and continues to
preserve every ordered block ID and its exact text. The extraction and
correction-policy versions are unchanged; saved prompt v5/v3 histories
retain their original mechanical interpretation.

The archived [v5 content review](../corpus/second-round/acceptance/reading-review-20260912-v5.md)
provides concrete counterexamples and uncertain interpretations separately.
Prompt changes require fresh complete-chapter generation and independent
review to establish any content-quality improvement; unit tests only verify
rendering, correction boundaries and replay.

## Whole-chapter joint translation/extraction + person states (C2-R3-T02)

> 本节描述 C2-R3 生产 0.3 联合路径（Issue #620，Task C2-R3-T02）。
> 契约权威见 [person-state-reading.md](person-state-reading.md) §§3–4；本节只说明
> 生成/provider 落点，不复制规范。上文 C2-R1 0.1 与 C2-R2 0.2 小节保持不变。

New production emits `chronicle.chapter-candidate / 0.3` — the frozen 0.2
reading joint product plus one `person_states` block — in the *same*
whole-chapter request. There is no per-segment state call and no read-time
state generation.

- **Single version registration.** `persistence/chapter_contract.py` extends
  its registry to `CANDIDATE_VERSIONS = ("0.1", "0.2", "0.3")`,
  `ARTIFACT_VERSIONS = ("0.1", "0.2", "0.3")`, `PRODUCTION_CANDIDATE_VERSION
  = "0.3"`, `PRODUCTION_ARTIFACT_VERSION = "0.3"` and the 0.3 schema
  paths/IDs. 0.1/0.2 stay frozen and retrievable; no second registry is
  created.
- **One whole-chapter call + at most one whole-chapter correction.**
  `chapter_prompt.render_chapter_prompt` renders the reading guide plus the
  person-state guide on top of the joint guide (phase facts/evidence/reading
  binding, parent/quotation subject discipline, shared chapter-local refs,
  action role vs. lasting state, recommendation/posthumous attest-only,
  `unassessed` candidates and local-ref/ID discipline). Both the initial and
  the correction prompt carry the full normalized text; a correction still
  requires one complete regenerated chapter product (never only the state
  array).
- **T01 validator reused, not duplicated.** `chapter_extraction.extract_chapter`
  dispatches by request version: 0.1 → `chapter_contract`, 0.2 →
  `reading_contract`, 0.3 → the T01
  `person_state_contract.validate_person_state_candidate` /
  `accept_person_state_candidate` (which itself reuses the frozen 0.2 reading
  validator on the subset). A 0.3 request can never silently downgrade; an
  unregistered version fails closed as `unsupported_candidate_version` before
  any model call. Missing `person_states`, capacity/truncation and unknown
  enums reject the whole joint product.
- **Consumer-side error categories.** A full-validation failure records
  `error.categories` (`schema_validation`, `reading`,
  `person_state_coverage`, `person_state_refs`, `person_state_phase`,
  `person_state_types`, `person_state_continuity`, `limits`, `canonical_id`).
- **Fingerprints/run history.** `fingerprints` records `candidate_schema`
  (`.../0.3`), `prompt_version` (`c2r3-chapter-prompt-v4`),
  `extraction_version` (`c2r3-extraction-v2`), `correction_policy_version`
  (see the shared correction-integrity procedure above), and for 0.3 the
  `person_state_schema` / `person_state_contract` / `person_state_limits`
  (plus the reading bindings), so model/contract/limit versions stay
  distinguishable.
- **Provider/fixture parity.** `worker/extraction_model_schema.py` keeps the
  frozen 0.1/0.2 projections and adds
  `person_state_chapter_candidate_model_schema()` with the required
  `person_states` block; `chapter_candidate_text_format()` now returns the
  production 0.3 format and `chapter_candidate_text_format_for(version)`
  selects 0.1/0.2/0.3. `model_provider.build_chapter_model(...)` defaults to
  0.3 and keeps the 4 MiB response cap / explicit output-token budget.
  `fixture_model.build_person_state_chapter_candidate` /
  `models_from_person_state_chapter_fixture_pack` emit the same 0.3 shape from
  one whole-chapter request.
- **Still worker-owned.** Model run identity, lease-fenced persistence, the
  atomic publish transaction, and the worker's `schema_versions` selection
  (including `chapter_stage`) remain with the production/publication task
  (T08); this task delivers the generation and provider layer only.

Unit suites: `persistence/test_person_state_extraction_unit.py`,
`worker/test_person_state_provider_unit.py`; the transport-retry and 0.1/0.2
regression suites above stay in place.
