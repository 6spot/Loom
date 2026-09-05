"""Explicit deterministic model-boundary fixtures for Chronicle development.

The provider implements the same ``complete(prompt) -> str`` boundary used by
C1-T6 extraction and C1-T12 Reader Presentation. Fixture mode therefore still
runs real source loading, segmentation, contract validation, assembly,
resolution/review, canonical publication, and presentation persistence.

It is development-only, source-grounded, explicit, and fail closed. Production
must leave ``CHRONICLE_MODEL_FIXTURE_PACK`` unset.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common import PersistenceError

FIXTURE_SCHEMA = "chronicle.model-fixture-pack"
FIXTURE_VERSION = "0.1"
EXTRACTION_MODEL_SUFFIX = "extract"
PRESENTATION_MODEL_SUFFIX = "present"

_PREDICATE_TEXT = {
    "died": "去世",
    "appointed": "获任相关职务",
    "held_office": "担任相关职务",
    "attacked": "发动或参与进攻",
    "fought": "参与战斗",
    "retreated": "撤退",
    "surrendered_to": "投降",
    "gained_territory": "取得相关地区",
    "moved_to": "发生地点迁移",
    "stationed_at": "驻屯于相关地点",
    "succeeded": "发生继承或接任",
    "outcome": "出现了史料所记载的结果",
    "affected": "发生了史料所记载的变化",
}


def _require_text(value: Any, description: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PersistenceError(f"{description} must be a non-empty string")
    return value.strip()


def _load_pack(path: Path | str) -> dict[str, Any]:
    fixture_path = Path(path).expanduser()
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersistenceError(
            f"cannot read Chronicle model fixture pack {fixture_path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise PersistenceError("Chronicle model fixture pack must be a JSON object")
    if payload.get("schema") != FIXTURE_SCHEMA or payload.get("version") != FIXTURE_VERSION:
        raise PersistenceError("unsupported Chronicle model fixture pack schema/version")
    _require_text(payload.get("model_version"), "fixture model_version")
    extraction = payload.get("extraction")
    presentation = payload.get("presentation")
    if not isinstance(extraction, dict) or not isinstance(presentation, dict):
        raise PersistenceError(
            "Chronicle model fixture pack requires extraction and presentation objects"
        )
    rules = extraction.get("rules")
    if not isinstance(rules, list):
        raise PersistenceError("fixture extraction.rules must be an array")
    seen: set[str] = set()
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise PersistenceError(f"fixture extraction rule {index} must be an object")
        rule_id = _require_text(rule.get("id"), f"fixture extraction rule {index} id")
        if rule_id in seen:
            raise PersistenceError(f"duplicate fixture extraction rule id {rule_id!r}")
        seen.add(rule_id)
        _require_text(rule.get("document"), f"fixture extraction rule {rule_id} document")
        evidence = _require_text(rule.get("evidence"), f"fixture extraction rule {rule_id} evidence")
        if "\n" in evidence:
            raise PersistenceError(
                f"fixture extraction rule {rule_id} evidence must be one exact inline substring"
            )
        subject = rule.get("subject")
        if not isinstance(subject, dict):
            raise PersistenceError(f"fixture extraction rule {rule_id} subject must be an object")
        _require_text(subject.get("name"), f"fixture extraction rule {rule_id} subject.name")
        _require_text(subject.get("type"), f"fixture extraction rule {rule_id} subject.type")
        if subject.get("mention") is not None:
            _require_text(subject.get("mention"), f"fixture extraction rule {rule_id} subject.mention")
        _require_text(rule.get("predicate"), f"fixture extraction rule {rule_id} predicate")
        event = rule.get("event")
        if not isinstance(event, dict):
            raise PersistenceError(f"fixture extraction rule {rule_id} event must be an object")
        _require_text(event.get("type"), f"fixture extraction rule {rule_id} event.type")
        _require_text(event.get("title"), f"fixture extraction rule {rule_id} event.title")
    if presentation.get("mode") != "claim-template-zh-CN-v1":
        raise PersistenceError(
            "fixture presentation.mode must be 'claim-template-zh-CN-v1'"
        )
    return payload


def _between(value: str, start: str, end: str, description: str) -> str:
    start_at = value.find(start)
    if start_at < 0:
        raise PersistenceError(f"fixture model prompt is missing {description} start marker")
    start_at += len(start)
    end_at = value.find(end, start_at)
    if end_at < 0:
        raise PersistenceError(f"fixture model prompt is missing {description} end marker")
    return value[start_at:end_at]


def _json_block(prompt: str, start: str, end: str, description: str) -> dict[str, Any]:
    raw = _between(prompt, start, end, description)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PersistenceError(f"fixture extraction prompt {description} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise PersistenceError(f"fixture extraction prompt {description} must be an object")
    return value


def _extraction_prompt_parts(
    prompt: str,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    section = _json_block(prompt, "\nSECTION\n", "\n\nDOCUMENT", "SECTION")
    document = _json_block(
        prompt, "\nDOCUMENT\n", "\n\nINHERITED CONTEXT", "DOCUMENT"
    )
    chunk_text = _between(
        prompt,
        "---BEGIN CHUNK---\n",
        "\n---END CHUNK---",
        "CHUNK SOURCE TEXT",
    )
    return section, document, chunk_text


def _presentation_context(prompt: str) -> dict[str, Any]:
    marker = "INPUT:\n"
    at = prompt.rfind(marker)
    if at < 0:
        raise PersistenceError("fixture presentation prompt is missing INPUT JSON")
    try:
        context = json.loads(prompt[at + len(marker) :])
    except json.JSONDecodeError as exc:
        raise PersistenceError("fixture presentation INPUT is invalid JSON") from exc
    if not isinstance(context, dict):
        raise PersistenceError("fixture presentation INPUT must be an object")
    return context


def _meta() -> dict[str, Any]:
    return {
        "method": "model",
        "job_id": "chronicle-c1-t13-fixture",
        "confidence": 1.0,
    }


def _entity_key(spec: dict[str, Any]) -> tuple[str, str]:
    return (
        _require_text(spec.get("name"), "fixture entity name"),
        _require_text(spec.get("type"), "fixture entity type"),
    )


def _mention(spec: dict[str, Any]) -> str:
    return _require_text(spec.get("mention") or spec.get("name"), "fixture entity mention")


def _build_extraction_bundle(
    *,
    section: dict[str, Any],
    document: dict[str, Any],
    chunk_text: str,
    rules: list[dict[str, Any]],
) -> dict[str, Any]:
    title = _require_text(document.get("title"), "fixture extraction document title")
    section_label = _require_text(section.get("label"), "fixture extraction section label")
    matched = [
        rule
        for rule in rules
        if rule.get("document") == title and str(rule.get("evidence", "")) in chunk_text
    ]

    entities: list[dict[str, Any]] = []
    entity_ids: dict[tuple[str, str], str] = {}

    def entity_ref(spec: dict[str, Any], evidence: str) -> str:
        key = _entity_key(spec)
        mention = _mention(spec)
        if mention not in evidence:
            raise PersistenceError(
                f"fixture entity mention {mention!r} is not present in exact evidence"
            )
        existing = entity_ids.get(key)
        if existing is not None:
            return existing
        ref = f"ent_{len(entities) + 1:03d}"
        entity_ids[key] = ref
        name, kind = key
        entities.append(
            {
                "temp_id": ref,
                "kind": "entity",
                "type": kind,
                "canonical_name": name,
                "aliases": [],
                "mentions": [{"text": mention}],
                "resolution": {"status": "unresolved"},
                "extraction": _meta(),
            }
        )
        return ref

    events: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    for rule in matched:
        evidence = str(rule["evidence"])
        subject_spec = rule["subject"]
        subject_ref = entity_ref(subject_spec, evidence)
        claim_object: dict[str, Any] | None = None
        participant_refs = [subject_ref]
        places: list[str] = []
        object_spec = rule.get("object")
        if isinstance(object_spec, dict):
            kind = object_spec.get("kind")
            if kind == "literal":
                claim_object = {"kind": "literal", "value": object_spec.get("value")}
            elif kind == "entity":
                target = object_spec.get("entity")
                if not isinstance(target, dict):
                    raise PersistenceError(
                        f"fixture rule {rule['id']} object.entity must be an object"
                    )
                target_ref = entity_ref(target, evidence)
                claim_object = {"kind": "entity_ref", "ref": target_ref}
                participant_refs.append(target_ref)
                if target.get("type") == "place":
                    places.append(target_ref)
            else:
                raise PersistenceError(
                    f"fixture rule {rule['id']} has unsupported object kind {kind!r}"
                )
        events.append(
            {
                "temp_id": f"evt_{len(events) + 1:03d}",
                "kind": "event",
                "type": rule["event"]["type"],
                "title": rule["event"]["title"],
                "time": None,
                "participants": [
                    {
                        "entity_ref": ref,
                        "role": "subject" if index == 0 else "related",
                    }
                    for index, ref in enumerate(dict.fromkeys(participant_refs))
                ],
                "places": list(dict.fromkeys(places)),
                "extraction": _meta(),
            }
        )
        claims.append(
            {
                "temp_id": f"clm_{len(claims) + 1:03d}",
                "kind": "claim",
                "subject": {"kind": "entity_ref", "ref": subject_ref},
                "predicate": rule["predicate"],
                "object": claim_object,
                "time": None,
                "evidence": {
                    "text": evidence,
                    "source_ref": "src_001",
                    "locator": {"work": "三國志", "section": section_label},
                },
                "assessment": {"status": "unassessed"},
                "extraction": _meta(),
            }
        )

    return {
        "schema_version": "0.1",
        "source": {
            "temp_id": "src_001",
            "kind": "source",
            "source_type": "book",
            "title": title,
            "author": "陳壽",
            "language": "lzh",
            "extraction": _meta(),
        },
        "entities": entities,
        "events": events,
        "claims": claims,
        "warnings": [],
    }


def _first_claim(context: dict[str, Any]) -> dict[str, Any]:
    for rep in context.get("representations") or []:
        for entry in rep.get("claims") or []:
            if isinstance(entry, dict) and isinstance(entry.get("claim"), dict):
                return entry
    raise PersistenceError("fixture presentation context contains no direct Claim")


def _target_label(context: dict[str, Any]) -> str:
    for rep in context.get("representations") or []:
        record = rep.get("record") if isinstance(rep, dict) else None
        if not isinstance(record, dict):
            continue
        for key in ("canonical_name", "title"):
            value = record.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "该历史对象"


def _build_presentation_candidate(context: dict[str, Any]) -> dict[str, Any]:
    claim_entry = _first_claim(context)
    claim = claim_entry["claim"]
    bundle = _require_text(
        claim_entry.get("bundle"), "fixture presentation Claim bundle"
    )
    ref = _require_text(claim_entry.get("ref"), "fixture presentation Claim ref")
    predicate = str(claim.get("predicate") or "")
    label = _target_label(context)
    phrase = _PREDICATE_TEXT.get(predicate, "有一项直接的史料记录")
    evidence = claim.get("evidence") if isinstance(claim.get("evidence"), dict) else {}
    evidence_text = str(evidence.get("text") or "").strip()
    if not evidence_text:
        raise PersistenceError("fixture presentation Claim has no evidence text")
    if len(evidence_text) > 180:
        evidence_text = evidence_text[:177] + "…"
    claim_ref = {"bundle": bundle, "ref": ref}
    blocks: list[dict[str, Any]] = [
        {
            "block_kind": "overview",
            "epistemic_mode": "fact_summary",
            "text": f"{label}{phrase}。",
            "claim_refs": [claim_ref],
        },
        {
            "block_kind": "source_notes",
            "epistemic_mode": "source_report",
            "text": f"对应史料原文为「{evidence_text}」。",
            "claim_refs": [claim_ref],
        },
    ]
    constraints = context.get("constraints")
    if isinstance(constraints, dict) and constraints.get("requires_uncertainty") is True:
        blocks.append(
            {
                "block_kind": "uncertainty",
                "epistemic_mode": "uncertainty",
                "text": "现有来源或身份解析仍包含不确定性，因此这里保留该不确定性，不把它改写成确定事实。",
                "claim_refs": [claim_ref],
            }
        )
    return {
        "schema": "chronicle.reader-presentation",
        "version": "0.1",
        "target_kind": context.get("target_kind"),
        "canonical_id": context.get("canonical_id"),
        "language": "zh-CN",
        "blocks": blocks,
    }


@dataclass(frozen=True)
class FixtureExtractionModel:
    name: str
    rules: tuple[dict[str, Any], ...]

    def complete(self, prompt: str) -> str:
        if not isinstance(prompt, str) or not prompt:
            raise PersistenceError("fixture extraction prompt must be non-empty text")
        section, document, chunk_text = _extraction_prompt_parts(prompt)
        bundle = _build_extraction_bundle(
            section=section,
            document=document,
            chunk_text=chunk_text,
            rules=list(self.rules),
        )
        return json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class FixturePresentationModel:
    name: str

    def complete(self, prompt: str) -> str:
        if not isinstance(prompt, str) or not prompt:
            raise PersistenceError("fixture presentation prompt must be non-empty text")
        candidate = _build_presentation_candidate(_presentation_context(prompt))
        return json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))


def models_from_fixture_pack(
    path: Path | str,
) -> tuple[FixtureExtractionModel, FixturePresentationModel]:
    """Load one explicit development fixture pack and expose both C1 models."""
    payload = _load_pack(path)
    version = _require_text(payload.get("model_version"), "fixture model_version")
    rules = tuple(payload["extraction"]["rules"])
    return (
        FixtureExtractionModel(
            name=f"fixture:{version}:{EXTRACTION_MODEL_SUFFIX}", rules=rules
        ),
        FixturePresentationModel(
            name=f"fixture:{version}:{PRESENTATION_MODEL_SUFFIX}"
        ),
    )
