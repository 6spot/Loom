#!/usr/bin/env python3
"""TEMP ONLY: apply the candidate live-model v5 changes in a runner workspace."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PERSIST = ROOT / "apps" / "chronicle" / "persistence"


def replace_once(text: str, old: str, new: str, name: str) -> str:
    if old in text:
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise SystemExit(f"{name} anchor not found")


def patch_extraction() -> None:
    path = PERSIST / "extraction.py"
    text = path.read_text()
    old_time = "\n".join(
        [
            '    if not isinstance(normalized, dict):',
            '        errors.append(f"{owner} time.normalized must be an object")',
            '        return',
            '    # Normalized precision is never invented at the chunk layer.',
            '    if normalized.get("month") is not None:',
            '        errors.append(f"{owner} fabricates normalized month from traditional calendar")',
            '    if normalized.get("day") is not None:',
            '        errors.append(f"{owner} fabricates normalized day from traditional calendar")',
            '    year = normalized.get("year")',
            '    if year is not None and (verified_year is None or year != verified_year):',
            '        errors.append(',
            '            f"{owner} normalized year {year!r} is not the document-verified year"',
            '        )',
        ]
    )
    new_time = "\n".join(
        [
            '    if normalized is not None and not isinstance(normalized, dict):',
            '        errors.append(f"{owner} time.normalized must be an object or null")',
            '        return',
            '    # Canonical schema permits normalized=null when no safe conversion exists.',
            '    # Only inspect normalized precision when the model actually supplies an object.',
            '    if isinstance(normalized, dict):',
            '        if normalized.get("month") is not None:',
            '            errors.append(f"{owner} fabricates normalized month from traditional calendar")',
            '        if normalized.get("day") is not None:',
            '            errors.append(f"{owner} fabricates normalized day from traditional calendar")',
            '        year = normalized.get("year")',
            '        if year is not None and (verified_year is None or year != verified_year):',
            '            errors.append(',
            '                f"{owner} normalized year {year!r} is not the document-verified year"',
            '            )',
        ]
    )
    text = replace_once(text, old_time, new_time, "normalized-time")

    if "fallback_without_snapshot" not in text:
        start = text.index(
            "    fallback = extraction_prompt_contract.render_compact_correction_prompt("
        )
        end_marker = "    return None"
        end = text.index(end_marker, start) + len(end_marker)
        replacement = "\n".join(
            [
                "    fallback = extraction_prompt_contract.render_compact_correction_prompt(",
                "        chunk_text=chunk_text,",
                '        section=request["request_meta"]["section"],',
                "        document=document,",
                "        context_input=context_input,",
                "        validation_errors=correction_errors,",
                "        previous_candidate=previous_candidate,",
                "    )",
                "    if len(fallback) <= config.max_prompt_chars:",
                "        return fallback",
                "    fallback_without_snapshot = extraction_prompt_contract.render_compact_correction_prompt(",
                "        chunk_text=chunk_text,",
                '        section=request["request_meta"]["section"],',
                "        document=document,",
                "        context_input=context_input,",
                "        validation_errors=correction_errors,",
                "        previous_candidate=None,",
                "    )",
                "    if len(fallback_without_snapshot) <= config.max_prompt_chars:",
                "        return fallback_without_snapshot",
                "    return None",
            ]
        )
        text = text[:start] + replacement + text[end:]
    path.write_text(text)


def patch_prompt() -> None:
    path = PERSIST / "extraction_prompt.py"
    text = path.read_text()
    for old in ('PROMPT_VERSION = "c1t6-prompt-v3"', 'PROMPT_VERSION = "c1t6-prompt-v4"'):
        if old in text:
            text = text.replace(old, 'PROMPT_VERSION = "c1t6-prompt-v5"', 1)
            break
    if 'PROMPT_VERSION = "c1t6-prompt-v5"' not in text:
        raise SystemExit("prompt version anchor not found")

    old_guide = '''source: {temp_id,kind:"source",source_type,title,language,extraction,...optional source fields}
entity: {temp_id,kind:"entity",type,canonical_name,aliases,mentions:[{text,contextual?}],resolution:{status,canonical_id?,candidate_ids?},extraction,...optional fields}
event: {temp_id,kind:"event",type,title,time,participants:[{entity_ref,role}],places:[entity-temp-id,...],extraction,...optional summary/parent_event_ref}
claim: {temp_id,kind:"claim",subject:REF,predicate,object:null|REF|LITERAL,time,evidence:{text,source_ref,locator},assessment:{status:"unassessed",note?},extraction}
warning: {type,severity:"info"|"warning"|"error",message,refs?}
REF: {kind:"entity_ref"|"event_ref",ref:temp-id}
LITERAL: {kind:"literal",value:any-json-value}'''
    new_guide = '''TOP LEVEL keys are exactly: schema_version, source, entities, events, claims, warnings. Use singular `source`, never `sources`.
source: {temp_id,kind:"source",source_type,title,language,extraction,...optional source fields}; source_type is one of book, article, web, dataset, manuscript, other. For historical works use "book"; never invent genre labels.
entity: {temp_id,kind:"entity",type,canonical_name,aliases,mentions:[{text,contextual?}],resolution:{status,canonical_id?,candidate_ids?},extraction,...optional fields}. mentions items MUST be objects; at least one mentions[].text must preserve an exact CHUNK SOURCE TEXT surface, with no simplified/traditional or spelling normalization. resolution.status is only unresolved|resolved|new|ambiguous; do not invent basis/explicit/textual_group fields or statuses.
event: {temp_id,kind:"event",type,title,time,participants:[{entity_ref:"ent_001",role:"..."}],places:["ent_002",...],extraction,...optional summary/parent_event_ref}. participant.entity_ref and every places item are STRING temp-ids, never REF objects.
claim: {temp_id,kind:"claim",subject:REF,predicate,object:null|REF|LITERAL,time,evidence:{text,source_ref,locator:{work?,section?,chapter?,volume?,paragraph?,fixture?}},assessment:{status:"unassessed",note?},extraction}. evidence.source_ref MUST equal emitted source.temp_id; locator is an OBJECT and locator.section must equal SECTION.label.
warning: {type,severity:"info"|"warning"|"error",message,refs?}
REF: {kind:"entity_ref"|"event_ref",ref:temp-id}; use REF only for Claim subject/object, not Event participant.entity_ref.
LITERAL: {kind:"literal",value:any-json-value}. Claim predicate must be lowercase ASCII snake_case. All refs must target temp_ids emitted in this same bundle.'''
    text = replace_once(text, old_guide, new_guide, "full-guide")

    old_core = '''source={temp_id,kind:"source",source_type,title,language,extraction}
entity={temp_id,kind:"entity",type,canonical_name,aliases,mentions,resolution,extraction}
event={temp_id,kind:"event",type,title,time,participants:[{entity_ref,role}],places:[temp-id,...],extraction}
claim={temp_id,kind:"claim",subject:{kind,ref},predicate,object,time,evidence:{text,source_ref,locator},assessment:{status:"unassessed"},extraction}
warning={type,severity,message,refs?}; extraction={method:"model",job_id:null|string,confidence:null|0..1}.'''
    new_core = '''top-level exactly {schema_version,source,entities,events,claims,warnings}; singular source only.
source={temp_id,kind:"source",source_type,title,language,extraction}; source_type=book|article|web|dataset|manuscript|other.
entity={temp_id,kind:"entity",type,canonical_name,aliases,mentions:[{text,contextual?}],resolution:{status},extraction}; resolution.status=unresolved|resolved|new|ambiguous; mention text preserves exact source glyphs.
event={temp_id,kind:"event",type,title,time,participants:[{entity_ref:"ent_001",role:"..."}],places:["ent_002"],extraction}; entity_ref/places are STRING temp-ids.
claim={temp_id,kind:"claim",subject:{kind:"entity_ref"|"event_ref",ref},predicate,object:null|REF|LITERAL,time,evidence:{text,source_ref,locator:{section,...}},assessment:{status:"unassessed"},extraction}; locator is object; evidence/name surfaces are exact source text; predicate is ASCII snake_case; all refs target emitted temp_ids.
warning={type,severity,message,refs?}; extraction={method:"model",job_id:null|string,confidence:null|0..1}.'''
    text = replace_once(text, old_core, new_core, "core-guide")

    grounding_anchor = "- Use only CHUNK SOURCE TEXT plus explicit SECTION/DOCUMENT metadata and bounded INHERITED CONTEXT. Never add outside historical knowledge.\n"
    grounding_line = "- Preserve source Unicode surfaces exactly for entity mentions and Claim evidence: never convert simplified/traditional characters, normalize spelling, or paraphrase evidence.\n"
    if grounding_line not in text:
        if grounding_anchor not in text:
            raise SystemExit("grounding anchor not found")
        text = text.replace(grounding_anchor, grounding_anchor + grounding_line, 1)

    start = text.index("def render_compact_correction_prompt(")
    prefix = text[:start]
    tail = '''def _repair_snapshot(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded structural snapshot of a prior candidate for repair only."""
    def ids(name: str) -> list[str]:
        items = candidate.get(name)
        if not isinstance(items, list):
            return []
        return [str(item.get("temp_id")) for item in items if isinstance(item, dict) and item.get("temp_id")]

    def pick(record: Any, keys: tuple[str, ...]) -> dict[str, Any] | None:
        if not isinstance(record, dict):
            return None
        return {key: record[key] for key in keys if key in record}

    entities = candidate.get("entities") if isinstance(candidate.get("entities"), list) else []
    events = candidate.get("events") if isinstance(candidate.get("events"), list) else []
    claims = candidate.get("claims") if isinstance(candidate.get("claims"), list) else []
    warnings = candidate.get("warnings") if isinstance(candidate.get("warnings"), list) else []
    return {
        "schema_version": candidate.get("schema_version"),
        "source": pick(candidate.get("source"), ("temp_id", "kind", "source_type", "title", "language", "extraction")),
        "record_counts": {"entities": len(entities), "events": len(events), "claims": len(claims), "warnings": len(warnings)},
        "temp_ids": {"entities": ids("entities"), "events": ids("events"), "claims": ids("claims")},
        "representative_entity": pick(entities[0] if entities else None, ("temp_id", "kind", "type", "canonical_name", "aliases", "mentions", "resolution", "extraction")),
        "representative_event": pick(events[0] if events else None, ("temp_id", "kind", "type", "title", "time", "participants", "places", "parent_event_ref", "extraction")),
        "representative_claim": pick(claims[0] if claims else None, ("temp_id", "kind", "subject", "predicate", "object", "time", "evidence", "assessment", "extraction")),
        "representative_warning": pick(warnings[0] if warnings else None, ("type", "severity", "refs")),
    }


def render_compact_correction_prompt(
    *,
    chunk_text: str,
    section: dict[str, Any],
    document: dict[str, Any],
    context_input: dict[str, Any],
    validation_errors: list[str],
    previous_candidate: dict[str, Any] | None = None,
) -> str:
    """Render a small repair envelope retaining source/context and candidate inventory."""
    snapshot = ""
    if isinstance(previous_candidate, dict):
        snapshot = (
            "\nPREVIOUS CANDIDATE REPAIR SNAPSHOT (repair aid only; may contain invalid fields)\n"
            + _json(_repair_snapshot(previous_candidate))
            + "\nPreserve its record inventory/distinct grounded facts while repairing invalid shapes; full prior response remains in ChunkRun history.\n"
        )
    return f'''Chronicle COMPACT CORRECTION RE-ASK. Return one complete compact JSON object only.
{MODEL_CONTRACT_CORE}
REPAIR RULES: source/context only; no outside facts; exact Unicode Claim evidence substring; inherited context is never evidence/authority; ambiguity stays unresolved; no canonical IDs; assessment=unassessed; no invented normalized month/day/year; preserve distinct facts; ontology_gap when predicate does not fit.
VALIDATION DIAGNOSTICS
{_json(validation_errors)}
{snapshot}SECTION
{_json(section)}

DOCUMENT
{_json(document)}

INHERITED CONTEXT (full bounded state; interpretation only)
{_json(context_input)}

CHUNK SOURCE TEXT
---BEGIN CHUNK---
{chunk_text}
---END CHUNK---
'''
'''
    path.write_text(prefix + tail)


def patch_tests() -> None:
    unit = PERSIST / "test_extraction_unit.py"
    text = unit.read_text().replace('"c1t6-prompt-v3"', '"c1t6-prompt-v5"').replace('"c1t6-prompt-v4"', '"c1t6-prompt-v5"')
    marker = '    def test_paraphrased_evidence_fails_grounding(self) -> None:\n'
    test_name = "test_canonical_normalized_null_is_not_rejected_by_mechanical_validator"
    if test_name not in text:
        addition = "\n".join(
            [
                '    def test_canonical_normalized_null_is_not_rejected_by_mechanical_validator(self) -> None:',
                '        bundle = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")',
                '        bundle["events"][0]["time"]["normalized"] = None',
                '        bundle["claims"][0]["time"]["normalized"] = None',
                '        report = self.validate(bundle)',
                '        self.assertTrue(report["passed"], X.flatten_validation_errors(report))',
                '',
                '',
            ]
        )
        if marker not in text:
            raise SystemExit("unit test anchor not found")
        text = text.replace(marker, addition + marker, 1)
    unit.write_text(text)

    r8 = PERSIST / "test_extraction_r8_contract_unit.py"
    text = r8.read_text().replace('"c1t6-prompt-v4"', '"c1t6-prompt-v5"').replace('"c1t6-prompt-v3"', '"c1t6-prompt-v5"')
    assertion = '        self.assertIn("SECTION/DOCUMENT/CONTEXT are input metadata only", prompt)\n'
    extra = '        self.assertIn("participant.entity_ref and every places item are STRING temp-ids", prompt)\n        self.assertIn("never convert simplified/traditional", prompt)\n'
    if extra not in text:
        if assertion not in text:
            raise SystemExit("R8 prompt assertion anchor not found")
        text = text.replace(assertion, assertion + extra, 1)
    r8.write_text(text)

    limits = PERSIST / "test_extraction_live_limits_unit.py"
    text = limits.read_text()
    old = '        self.assertNotIn("PREVIOUS CANDIDATE", provider.prompts[1])\n'
    first = text.find(old)
    if first >= 0:
        text = text[:first] + '        self.assertIn("PREVIOUS CANDIDATE REPAIR SNAPSHOT", provider.prompts[1])\n' + text[first + len(old):]
    # The near-8K test is allowed to use the no-snapshot fallback when inventory will not fit.
    second = text.find(old)
    if second >= 0:
        text = text[:second] + '        self.assertIn("COMPACT CORRECTION RE-ASK", provider.prompts[1])\n' + text[second + len(old):]
    limits.write_text(text)


def main() -> None:
    patch_extraction()
    patch_prompt()
    patch_tests()
    print("temp live v5 patch applied")


if __name__ == "__main__":
    main()
