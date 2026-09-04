# Reader Presentation v0.1

Reader Presentation is Chronicle's application-owned, derived reader layer. It makes canonical Events and Entities understandable in modern Chinese without becoming a historical truth authority.

## Authority boundary

The authority chain remains:

`Reader Presentation -> supporting Claim -> evidence -> Source`

Canonical Entity/Event identity, staged source records, Claims, evidence, assessments and Resolution Links remain authoritative in their existing layers. Presentation text cannot create a Claim, merge an identity, erase disagreement, or overwrite source material.

## Base language

C1 persists exactly one base reader language: `zh-CN`.

Other languages are outside the persisted Reader Presentation contract. A future translation projection may translate published blocks at request/cache time while preserving `block_id` and support bindings, but it must remain non-authoritative and must not create per-language historical truth records.

## Candidate contract

Generator output uses `apps/chronicle/ingestion/schemas/chronicle-reader-presentation-v0.1.schema.json`:

- `schema = chronicle.reader-presentation`
- `version = 0.1`
- target is exactly one canonical `entity` or `event`
- `language = zh-CN`
- content is an ordered list of atomic blocks
- each block has one `block_kind`, one `epistemic_mode`, modern-Chinese text and at least one `(bundle, Claim ref)` support

C1 block kinds are intentionally narrow: `overview`, `sequence`, `outcome`, `source_notes`, `uncertainty`. `why` / historical significance is not introduced here because unsupported causality must not be inferred by the presentation generator.

## Grounding rules

A candidate may use only the supplied target context. Every support Claim must:

1. already exist in `chronicle.staged_claims`;
2. directly refer to a source representation belonging to the canonical target;
3. carry non-empty `evidence.text` and `evidence.source_ref`;
4. be part of the exact generation input fingerprint.

Unknown or out-of-scope Claim refs reject the candidate. Blocks with no support reject the candidate. If the target context exposes a material disagreement or an uncertain identity/occurrence link, the candidate must include an `uncertainty` block supported by the relevant input Claims. Common historical knowledge outside Chronicle's supplied context must be omitted.

These checks establish provenance scope; they do not pretend that a mechanical validator can prove natural-language entailment. Readability/grounding inspection remains part of T12 acceptance, and future semantic validators may strengthen this boundary without changing Claim authority.

## Persistence and regeneration

`chronicle.reader_presentations`, `reader_presentation_blocks` and `reader_presentation_supports` are append-only projection tables. A successful regeneration creates a new `presentation_version` with an `input_fingerprint`, generator/model/prompt versions and a `supersedes_presentation_id` link. Old presentations remain auditable.

The current public projection is the greatest published `presentation_version` for a canonical target. Regeneration never mutates canonical UUIDs, staged records, Claims or evidence.

## Reader API / UI

Event and Entity detail responses may include a `reader_presentation` object. Public pages render it before source-heavy research material. Every block exposes its support Claim refs and resolved Claim/evidence payloads so readers can drill directly from modern prose to the source-grounded layer.

When no validated presentation exists, the API returns no presentation and the page falls back to the existing source-grounded detail rather than generating prose during the request.
