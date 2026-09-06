#!/usr/bin/env python3
"""TEMP ONLY: apply focused v5 prompt/validator corrections in runner workspace."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PERSIST = ROOT / "apps" / "chronicle" / "persistence"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old in text:
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise SystemExit(f"{label} anchor not found")


def patch_extraction() -> None:
    path = PERSIST / "extraction.py"
    text = path.read_text()
    old = "\n".join([
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
    ])
    new = "\n".join([
        '    if normalized is not None and not isinstance(normalized, dict):',
        '        errors.append(f"{owner} time.normalized must be an object or null")',
        '        return',
        '    # Canonical schema permits normalized=null when no safe conversion exists.',
        '    # Only inspect normalized precision when the model supplies an object.',
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
    ])
    path.write_text(replace_once(text, old, new, "normalized-time"))


def patch_prompt() -> None:
    path = PERSIST / "extraction_prompt.py"
    text = path.read_text()
    if 'PROMPT_VERSION = "c1t6-prompt-v3"' in text:
        text = text.replace('PROMPT_VERSION = "c1t6-prompt-v3"', 'PROMPT_VERSION = "c1t6-prompt-v5"', 1)
    elif 'PROMPT_VERSION = "c1t6-prompt-v4"' in text:
        text = text.replace('PROMPT_VERSION = "c1t6-prompt-v4"', 'PROMPT_VERSION = "c1t6-prompt-v5"', 1)
    elif 'PROMPT_VERSION = "c1t6-prompt-v5"' not in text:
        raise SystemExit("prompt-version anchor not found")

    full_start = text.index('source: {temp_id,kind:"source",source_type,title,language,extraction,...optional source fields}')
    full_end = text.index('extraction: {method:"model",job_id:null|string,confidence:null|0..1}', full_start)
    full_end = text.index('\n', full_end)
    full_replacement = "\n".join([
        'TOP LEVEL keys are exactly: schema_version, source, entities, events, claims, warnings. Use singular `source`, never `sources`.',
        'source: {temp_id,kind:"source",source_type,title,language,extraction,...optional source fields}; source_type is one of book, article, web, dataset, manuscript, other. For historical works use "book"; never invent genre labels.',
        'entity: {temp_id,kind:"entity",type,canonical_name,aliases,mentions:[{text,contextual?}],resolution:{status,canonical_id?,candidate_ids?},extraction,...optional fields}. mentions items MUST be objects. At least one mentions[].text must be an exact CHUNK SOURCE TEXT surface; NEVER convert simplified/traditional characters or normalize spelling. resolution.status is only unresolved|resolved|new|ambiguous; do not invent other resolution fields/statuses.',
        'event: {temp_id,kind:"event",type,title,time,participants:[{entity_ref:"ent_001",role:"..."}],places:["ent_002",...],extraction,...optional summary/parent_event_ref}. participant.entity_ref and every places item are STRING temp-ids, never REF objects.',
        'claim: {temp_id,kind:"claim",subject:REF,predicate,object:null|REF|LITERAL,time,evidence:{text,source_ref,locator:{work?,section?,chapter?,volume?,paragraph?,fixture?}},assessment:{status:"unassessed",note?},extraction}. Claim evidence.text is an exact Unicode CHUNK SOURCE TEXT substring; evidence.source_ref equals emitted source.temp_id; locator is an OBJECT and locator.section equals SECTION.label.',
        'warning: {type,severity:"info"|"warning"|"error",message,refs?}',
        'REF: {kind:"entity_ref"|"event_ref",ref:temp-id}; use REF only for Claim subject/object, not Event participant.entity_ref.',
        'LITERAL: {kind:"literal",value:any-json-value}. Claim predicate is lowercase ASCII snake_case. All refs target temp_ids emitted in this same bundle.',
        'extraction: {method:"model",job_id:null|string,confidence:null|0..1}',
    ]) + "\n"
    text = text[:full_start] + full_replacement + text[full_end:]

    core_start = text.index('source={temp_id,kind:"source",source_type,title,language,extraction}')
    core_end = text.index('warning={type,severity,message,refs?}; extraction={method:"model",job_id:null|string,confidence:null|0..1}.', core_start)
    core_end = text.index('\n', core_end)
    core_replacement = "\n".join([
        'top-level exactly {schema_version,source,entities,events,claims,warnings}; singular source only.',
        'source={temp_id,kind:"source",source_type,title,language,extraction}; source_type=book|article|web|dataset|manuscript|other.',
        'entity={temp_id,kind:"entity",type,canonical_name,aliases,mentions:[{text,contextual?}],resolution:{status},extraction}; resolution.status=unresolved|resolved|new|ambiguous; mention text preserves exact source glyphs.',
        'event={temp_id,kind:"event",type,title,time,participants:[{entity_ref:"ent_001",role:"..."}],places:["ent_002"],extraction}; entity_ref/places are STRING temp-ids.',
        'claim={temp_id,kind:"claim",subject:{kind:"entity_ref"|"event_ref",ref},predicate,object:null|REF|LITERAL,time,evidence:{text,source_ref,locator:{section,...}},assessment:{status:"unassessed"},extraction}; locator is object; evidence/name surfaces are exact source text; predicate is ASCII snake_case; all refs target emitted temp_ids.',
        'warning={type,severity,message,refs?}; extraction={method:"model",job_id:null|string,confidence:null|0..1}.',
    ]) + "\n"
    text = text[:core_start] + core_replacement + text[core_end:]

    anchor = '- Use only CHUNK SOURCE TEXT plus explicit SECTION/DOCUMENT metadata and bounded INHERITED CONTEXT. Never add outside historical knowledge.\n'
    line = '- Preserve source Unicode surfaces exactly for entity mentions and Claim evidence: never convert simplified/traditional characters, normalize spelling, or paraphrase evidence.\n'
    if line not in text:
        if anchor not in text:
            raise SystemExit("grounding anchor not found")
        text = text.replace(anchor, anchor + line, 1)
    path.write_text(text)


def patch_tests() -> None:
    unit = PERSIST / "test_extraction_unit.py"
    text = unit.read_text().replace('"c1t6-prompt-v3"', '"c1t6-prompt-v5"').replace('"c1t6-prompt-v4"', '"c1t6-prompt-v5"')
    test_name = 'test_canonical_normalized_null_is_not_rejected_by_mechanical_validator'
    if test_name not in text:
        marker = '    def test_paraphrased_evidence_fails_grounding(self) -> None:\n'
        addition = "\n".join([
            '    def test_canonical_normalized_null_is_not_rejected_by_mechanical_validator(self) -> None:',
            '        bundle = valid_bundle(CHUNK_0, "劉表卒", time_original="建安十三年")',
            '        bundle["events"][0]["time"]["normalized"] = None',
            '        bundle["claims"][0]["time"]["normalized"] = None',
            '        report = self.validate(bundle)',
            '        self.assertTrue(report["passed"], X.flatten_validation_errors(report))',
            '',
            '',
        ])
        if marker not in text:
            raise SystemExit("unit-test insertion anchor not found")
        text = text.replace(marker, addition + marker, 1)
    unit.write_text(text)

    r8 = PERSIST / "test_extraction_r8_contract_unit.py"
    text = r8.read_text().replace('"c1t6-prompt-v3"', '"c1t6-prompt-v5"').replace('"c1t6-prompt-v4"', '"c1t6-prompt-v5"')
    assertion = '        self.assertIn("SECTION/DOCUMENT/CONTEXT are input metadata only", prompt)\n'
    extra = '        self.assertIn("participant.entity_ref and every places item are STRING temp-ids", prompt)\n        self.assertIn("never convert simplified/traditional", prompt)\n'
    if extra not in text:
        if assertion not in text:
            raise SystemExit("R8 assertion anchor not found")
        text = text.replace(assertion, assertion + extra, 1)
    r8.write_text(text)


def main() -> None:
    patch_extraction()
    patch_prompt()
    patch_tests()
    print("focused v5 prompt/validator patch applied")


if __name__ == "__main__":
    main()
