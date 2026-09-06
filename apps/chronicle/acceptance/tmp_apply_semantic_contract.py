#!/usr/bin/env python3
"""TEMP ONLY: patch semantic prompt + normalized-null validator for live validation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PERSIST = ROOT / "apps" / "chronicle" / "persistence"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old in text:
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise SystemExit(f"{label} anchor not found")


extraction = PERSIST / "extraction.py"
text = extraction.read_text()
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
extraction.write_text(replace_once(text, old, new, "normalized-null validator"))

prompt = PERSIST / "extraction_prompt.py"
text = prompt.read_text()
text = replace_once(
    text,
    'PROMPT_VERSION = "c1t6-prompt-v3"',
    'PROMPT_VERSION = "c1t6-prompt-v4"',
    "prompt version",
)
anchor = "- Use only CHUNK SOURCE TEXT plus explicit SECTION/DOCUMENT metadata and bounded INHERITED CONTEXT. Never add outside historical knowledge.\n"
semantic = (
    "- Preserve CHUNK SOURCE TEXT Unicode surfaces exactly. Entity canonical_name/mentions and Claim evidence must never convert simplified/traditional characters, normalize spelling, or paraphrase an exact source surface.\n"
    "- A locally grounded entity must copy at least one exact mention surface from CHUNK SOURCE TEXT. If it exists only in inherited context, preserve that exact inherited surface and emit inherited_entity_context warning; otherwise omit it.\n"
    "- Event time must be null unless time.original_text is an exact CHUNK SOURCE TEXT substring or an exact inherited_time surface. Use normalized year only when DOCUMENT.verified_normalized_year supplies that exact mapping; otherwise normalized must be null.\n"
    "- Claim evidence.text must be one exact CHUNK SOURCE TEXT substring and evidence.locator.section must equal SECTION.label exactly.\n"
)
if semantic not in text:
    if anchor not in text:
        raise SystemExit("semantic prompt anchor not found")
    text = text.replace(anchor, anchor + semantic, 1)
prompt.write_text(text)

for filename in ("test_extraction_unit.py", "test_extraction_r8_contract_unit.py"):
    path = PERSIST / filename
    value = path.read_text().replace('"c1t6-prompt-v3"', '"c1t6-prompt-v4"')
    path.write_text(value)

unit = PERSIST / "test_extraction_unit.py"
text = unit.read_text()
test_name = "test_canonical_normalized_null_is_not_rejected_by_mechanical_validator"
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
        raise SystemExit("normalized-null test anchor not found")
    text = text.replace(marker, addition + marker, 1)
unit.write_text(text)

print("semantic contract patch applied")
