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

Generation reads the same effective published resolution artifacts as canonical
publication. A persisted `final` output replaces an `initial` artifact only for
the same job and exact source-bundle pair. Other jobs, imported C0 decisions and
unchanged artifacts are not superseded by timestamps. Initial artifacts and
their links remain available for audit. In-flight unpublished sources do not
change an existing target's generation context. The immutable staged
`record.resolution.status` is an extraction-time observation, not the current
review decision or permission to deny published canonical membership.

These checks establish provenance scope; they do not pretend that a mechanical validator can prove natural-language entailment. Readability/grounding inspection remains part of T12 acceptance, and future semantic validators may strengthen this boundary without changing Claim authority.

## Persistence and regeneration

`chronicle.reader_presentations`, `reader_presentation_blocks` and `reader_presentation_supports` are append-only projection tables. A successful regeneration creates a new `presentation_version` with an `input_fingerprint`, generator/model/prompt versions and a `supersedes_presentation_id` link. Old presentations remain auditable.

The current public projection is the greatest published `presentation_version` for a canonical target. Regeneration never mutates canonical UUIDs, staged records, Claims or evidence.

## Offline pipeline

The durable `present` stage is opt-in through a dedicated presentation-model provider. It does not reuse the extraction model implicitly. The worker freezes a canonical/Claim/evidence context, performs the model call with no PostgreSQL transaction open, then reacquires the ingestion-job lease and rechecks the input fingerprint before writing anything. Cancellation, lease takeover, or knowledge changes therefore win over stale generated prose.

The live Responses request uses a presentation-specific strict `text.format`
derived from the canonical candidate schema. Prompt `c1t12-reader-zh-v3` retains
the complete output instructions introduced in v2 and supplies
the exact output header (including `target_kind` and `canonical_id`), all block
fields, bounds and Claim-ref shape. The provider adapter adds explicit string
types to canonical const/enum fields and omits schema annotations and
`uniqueItems`, which is outside the documented
[Responses strict array subset](https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas).
The prompt still requires unique supports and the existing validator normalizes
duplicate refs. Missing/null/wrong target fields, out-of-scope Claims and omitted
required uncertainty still fail closed; model output is never patched with
missing target metadata. The candidate schema, Claim authority and immutable
persistence contract remain unchanged.

The prompt also requires source-bounded actor/recipient direction and reporting
attribution. A fragment that omits an action's recipient must not become a
claim that the target died or received a title. Source narration must not
become a person's self-claim, and reported rumors must remain reports. Modern
wording preserves the evidence's specificity (for example, `履` means shoes;
their material must not be invented). When the
bound evidence cannot support a paraphrase, quote the fragment or omit that
detail. Reader text uses ordinary Chinese source attribution rather than
internal field names or resolution enum values. Required uncertainty describes
the actual evidence boundary; a conservative disagreement flag alone does not
prove an identity conflict or turn complementary accounts into contradictory
ones.

The `Chronicle Live Model Contract` workflow checks real extraction plus Entity
and Event presentation before a new T17 run. Its presentation check uses the
retained C0 刘表 and 赤壁 examples in a fresh PostgreSQL test database and calls
the production context loader, generator, validators and persistence functions,
including exact-input adoption. It reports only metadata, hashes and counts.
To run that focused check with the configured live provider and an isolated test
PostgreSQL service, set `LOOM_TEST_POSTGRES_URL` and run:

```bash
python3 apps/chronicle/acceptance/live_presentation_contract.py
```

This preflight is regression evidence, not a substitute for full-source T17
ingestion, human review, readability inspection or browser acceptance.

Targets with no direct evidenced Claims are omitted rather than filled from model knowledge. Exact-input crash/retry adoption reuses the already-published projection without another model call. The resulting presentation and its job output remain explicitly `authoritative: false`.

## Reader API / UI

Event and Entity detail responses may include a `reader_presentation` object. Public pages render it before source-heavy research material. Every block exposes its support Claim refs and resolved Claim/evidence payloads so readers can drill directly from modern prose to the source-grounded layer.

When no validated presentation exists, the API returns no presentation and the page falls back to the existing source-grounded detail rather than generating prose during the request.

## T12 manual grounding/readability inspection

The initial inspection uses retained C0 historical artifacts rather than invented prose fixtures. The criterion is deliberately strict: a modern-Chinese sentence is acceptable only to the extent that the bound Claim/evidence can support it.

| Target | Supporting Claim / exact evidence | Accepted reader wording | Boundary checked |
| --- | --- | --- | --- |
| 赤壁之战 Event (`wudi/clm_024`) | `outcome = 不利`; evidence `不利` in 《三国志·魏书·武帝纪》 | `《武帝纪》对这场赤壁交战的结果记为“不利”。` | Does **not** add fire attack, casualty scale, strategic significance, or a stronger “惨败” characterization. |
| 刘表 Entity (`wudi/clm_008`) | `died`; evidence `表卒` in 《三国志·魏书·武帝纪》 | `《武帝纪》记载刘表去世。` | Modernizes `卒` without inventing cause, place, exact day, or consequence. |
| 孙权 Entity (`wuzhu/clm_008`) | `sent_forces`; evidence `权遣周瑜、程普等行` in 《三国志·吴书·吴主传》 | `《吴主传》记载，孙权派周瑜、程普等出兵。` | Preserves the explicit dispatch action; does not infer the later battle result into this block. |
| Naming actor in a fragment | `posthumously_named`; evidence `追谥曰孝愍皇帝` | `这段记载写有“追谥曰孝愍皇帝”，片段未明示受谥者。` | Does not invent the actor's death or turn the actor into the recipient. |
| 刘备 ancestry | `has_ancestry`; evidence `先主姓刘，讳备，字玄德，涿郡涿县人，汉景帝子中山靖王胜之后也` | `《先主传》记载，刘备字玄德，涿郡涿县人，是汉景帝之子中山靖王刘胜的后裔。` | Preserves the historian's attribution; does not change it to `刘备自称` without a supporting self-report. |

A tempting sentence such as `曹操在赤壁遭火攻击败，这成为三国格局的决定性转折` is intentionally outside T12 support for the inspected Event context: those causal/significance details are not licensed merely because they are familiar historical knowledge. Such prose must wait for supporting Chronicle Claims (and later causal interpretation semantics), not be smuggled in by the reader layer.

For final live acceptance, inspect the generated blocks against their bound
Claims and exact evidence, including action direction, reported versus asserted
content, omitted roles and retained uncertainty. Record the inspected
presentation IDs/hashes and a separate content-review verdict. Passing schema,
support-reference and browser checks does not establish natural-language
entailment; retain an automated PASS as process evidence when content review
fails, and keep final acceptance incomplete.
