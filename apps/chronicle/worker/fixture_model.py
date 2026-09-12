"""Explicit deterministic model-boundary fixtures for Chronicle development.

The provider implements the same ``complete(prompt) -> str`` boundary used by
C1-T6 extraction and C1-T12 Reader Presentation. Fixture mode therefore still
runs real source loading, segmentation, contract validation, assembly,
resolution/review, canonical publication, and presentation persistence.

It is development-only, source-grounded, explicit, and fail closed. Production
must leave ``CHRONICLE_MODEL_FIXTURE_PACK`` unset.

C2-R1-T06 adds an explicit chapter fixture (``FixtureChapterModel``) for the
chapter-candidate joint protocol. It emits the same model-candidate shape a
live chapter provider would produce (``chronicle.chapter-candidate / 0.1``
with full translation blocks and structure), bound to the pack's
``chapter_id``. Acceptance always runs the T01 canonical validator; the
fixture never synthesizes program-bound values (hashes, offsets, canonical
IDs, fingerprints). Unknown chapters and chapter drift fail closed: there is
no silent fallback to development output.
"""

from __future__ import annotations

import hashlib
import json
import re
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


# ---------------------------------------------------------------------------
# Chapter fixtures (C2-R1-T06)
# ---------------------------------------------------------------------------
# The chapter fixture emits ``chronicle.chapter-candidate / 0.1`` candidates
# with the same shape a live chapter provider produces: full translation
# blocks covering every required source block, bundle entities/events/claims,
# mentions, record_sources selections, and warnings. Every quote is grounded
# verbatim in the request's normalized chapter text; unknown chapters,
# chapter_id drift, and ungrounded mentions fail closed.
#
# The test prompt envelope below is fixture-test-only. Real chapter prompt
# construction belongs to C2-R1-T05 and worker wiring to C2-R1-T13; they may
# call ``build_chapter_candidate(request)`` directly with the program-owned
# request instead of going through ``complete(prompt)``.

CHAPTER_FIXTURE_SCHEMA = "chronicle.chapter-fixture-pack"
CHAPTER_FIXTURE_VERSION = "0.1"
CHAPTER_MODEL_SUFFIX = "chapter"

CHAPTER_REQUEST_START = "\nCHAPTER_REQUEST\n"
CHAPTER_REQUEST_END = "\n---END CHAPTER_REQUEST---"

_CHAPTER_ID_PATTERN = re.compile(r"ch_[0-9a-f]{24}")

# Production T05 prompt sections (chapter-production.md section 3): the
# joint renderer carries the whole chapter verbatim plus a JSON request
# header, so a development provider can rebuild the exact program-owned
# request without a second envelope.
_CHAPTER_T05_HEADER_MARKER = "CHAPTER REQUEST\n"
_CHAPTER_T05_REQUIRED_MARKER = (
    "REQUIRED BLOCKS (every listed block must be covered "
    "by translation source_block_ids)\n"
)
# Anchored to the renderer's exact section headers: bare "CHAPTER BLOCKS" /
# "FULL CHAPTER TEXT" also appear in the TRANSLATION_RULES prose, and
# ``str.find`` would otherwise match the rule sentence instead of the
# section (the fixture then reports zero blocks and fails closed).
_CHAPTER_T05_BLOCKS_MARKER = "CHAPTER BLOCKS (the whole chapter"
_CHAPTER_T05_TEXT_MARKER = "FULL CHAPTER TEXT (verbatim"
_CHAPTER_T05_TEXT_START = "---BEGIN CHAPTER---\n"
_CHAPTER_T05_TEXT_END = "\n---END CHAPTER---"
_CHAPTER_T05_BLOCK_RE = re.compile(
    r"\[(?P<block_id>[^\s\]]+) kind=(?P<kind>[^\s\]]+)"
    r" range=(?P<start>\d+):(?P<end>\d+)[^\]]*\]\n"
    r"(?P<content>.*?)\n---END (?P=block_id)---",
    re.DOTALL,
)

_CONTEXTUAL_ONLY_SURFACES = frozenset({"公", "王"})

_CHAPTER_ENTITY_TYPES = frozenset(
    {
        "person",
        "place",
        "polity",
        "organization",
        "army",
        "office",
        "group",
        "other",
    }
)

_CHAPTER_EVENT_TYPES = frozenset(
    {
        "political",
        "administrative",
        "military",
        "battle",
        "movement",
        "retreat",
        "death",
        "birth",
        "succession",
        "appointment",
        "surrender",
        "diplomatic",
        "epidemic",
        "territorial_change",
        "economic",
        "cultural",
        "other",
    }
)


def _chapter_request_fingerprint(request: dict[str, Any]) -> str | None:
    """Compute the T01 request fingerprint, or ``None`` when unavailable.

    The canonical implementation lives in T01 ``chapter_contract``; this
    helper resolves it lazily so fixture-only deployments never gain a hard
    import-time dependency on the persistence layout.
    """
    try:
        from chapter_contract import request_fingerprint
    except ImportError:
        try:
            from persistence.chapter_contract import (  # type: ignore[no-redef]
                request_fingerprint,
            )
        except ImportError:
            return None
    try:
        return str(request_fingerprint(request))
    except Exception:
        return None


def _load_chapter_pack(path: Path | str) -> dict[str, Any]:
    fixture_path = Path(path).expanduser()
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersistenceError(
            f"cannot read Chronicle chapter fixture pack {fixture_path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise PersistenceError("Chronicle chapter fixture pack must be a JSON object")
    if (
        payload.get("schema") != CHAPTER_FIXTURE_SCHEMA
        or payload.get("version") != CHAPTER_FIXTURE_VERSION
    ):
        raise PersistenceError(
            "unsupported Chronicle chapter fixture pack schema/version"
        )
    _require_text(payload.get("model_version"), "chapter fixture model_version")
    chapters = payload.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise PersistenceError("chapter fixture chapters must be a non-empty array")
    seen: set[str] = set()
    for index, spec in enumerate(chapters):
        if not isinstance(spec, dict):
            raise PersistenceError(f"chapter fixture entry {index} must be an object")
        chapter_id = _require_text(
            spec.get("chapter_id"), f"chapter fixture entry {index} chapter_id"
        )
        if not _CHAPTER_ID_PATTERN.fullmatch(chapter_id):
            raise PersistenceError(
                f"chapter fixture entry {index} chapter_id {chapter_id!r} "
                "must match ch_<24 hex>"
            )
        if chapter_id in seen:
            raise PersistenceError(
                f"duplicate chapter fixture chapter_id {chapter_id!r}"
            )
        seen.add(chapter_id)
        _require_text(
            spec.get("revision_id"), f"chapter fixture {chapter_id} revision_id"
        )
        _require_text(
            spec.get("source_title"), f"chapter fixture {chapter_id} source_title"
        )
        _require_text(
            spec.get("translation_text"),
            f"chapter fixture {chapter_id} translation_text",
        )
        entities = spec.get("entities")
        if not isinstance(entities, list) or not entities:
            raise PersistenceError(
                f"chapter fixture {chapter_id} entities must be a non-empty array"
            )
        for position, entity in enumerate(entities):
            if not isinstance(entity, dict):
                raise PersistenceError(
                    f"chapter fixture {chapter_id} entity {position} must be an object"
                )
            _require_text(entity.get("name"), f"chapter fixture {chapter_id} entity {position} name")
            entity_type = _require_text(
                entity.get("type"), f"chapter fixture {chapter_id} entity {position} type"
            )
            if entity_type not in _CHAPTER_ENTITY_TYPES:
                raise PersistenceError(
                    f"chapter fixture {chapter_id} entity {position} "
                    f"has unknown type {entity_type!r}"
                )
            _require_text(
                entity.get("mention"),
                f"chapter fixture {chapter_id} entity {position} mention",
            )
        event = spec.get("event")
        if not isinstance(event, dict):
            raise PersistenceError(f"chapter fixture {chapter_id} event must be an object")
        event_type = _require_text(event.get("type"), f"chapter fixture {chapter_id} event.type")
        if event_type not in _CHAPTER_EVENT_TYPES:
            raise PersistenceError(
                f"chapter fixture {chapter_id} has unknown event type {event_type!r}"
            )
        _require_text(event.get("title"), f"chapter fixture {chapter_id} event.title")
        predicate = spec.get("predicate", "affected")
        if not isinstance(predicate, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", predicate):
            raise PersistenceError(
                f"chapter fixture {chapter_id} predicate {predicate!r} "
                "must match ^[a-z][a-z0-9_]*$"
            )
        fingerprint = spec.get("request_fingerprint")
        if fingerprint is not None and (
            not isinstance(fingerprint, str) or not fingerprint.strip()
        ):
            raise PersistenceError(
                f"chapter fixture {chapter_id} request_fingerprint "
                "must be a non-empty string when present"
            )
    return payload


def _chapter_block_containing(
    blocks: list[dict[str, Any]], position: int
) -> dict[str, Any]:
    for block in blocks:
        if (
            isinstance(block, dict)
            and isinstance(block.get("start"), int)
            and isinstance(block.get("end"), int)
            and block["start"] <= position < block["end"]
        ):
            return block
    raise PersistenceError(
        f"fixture chapter quote at offset {position} falls outside every block"
    )


def _chapter_selection_for(
    *,
    quote: str,
    text: str,
    blocks: list[dict[str, Any]],
    owner: str,
) -> dict[str, Any]:
    """Build a verbatim-grounded selection for ``quote`` (fail closed)."""
    position = text.find(quote)
    if position < 0:
        raise PersistenceError(
            f"fixture chapter quote {quote!r} for {owner} "
            "is not present in the chapter text"
        )
    block = _chapter_block_containing(blocks, position)
    block_text = text[block["start"] : block["end"]]
    occurrence = block_text.count(quote)
    if occurrence < 1:  # pragma: no cover - defensive; find() already matched
        raise PersistenceError(
            f"fixture chapter quote {quote!r} for {owner} is unresolvable"
        )
    # First occurrence inside the containing block: deterministic and valid
    # because the quote verbatim occurs there exactly ``occurrence`` times.
    return {
        "first_block_id": block["block_id"],
        "last_block_id": block["block_id"],
        "quote": quote,
        "occurrence": 1,
    }


def _chapter_meta() -> dict[str, Any]:
    return {"method": "model", "job_id": None, "confidence": None}


def build_chapter_candidate(
    request: dict[str, Any], spec: dict[str, Any]
) -> dict[str, Any]:
    """Build a deterministic chapter candidate for one fixture chapter.

    ``request`` is the program-owned chapter request (chapter_id,
    normalized_text, blocks, required_block_ids); ``spec`` is one entry of
    a chapter fixture pack. The result carries only model-generatable
    fields and is meant to be checked by the T01 canonical validator.
    """
    if not isinstance(request, dict) or not isinstance(spec, dict):
        raise PersistenceError("fixture chapter request and spec must be objects")
    chapter_id = request.get("chapter_id")
    if chapter_id != spec.get("chapter_id"):
        raise PersistenceError(
            f"fixture chapter_id drift: request {chapter_id!r} vs "
            f"fixture {spec.get('chapter_id')!r}"
        )
    text = request.get("normalized_text")
    if not isinstance(text, str) or not text:
        raise PersistenceError("fixture chapter request normalized_text must be non-empty")
    blocks = request.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise PersistenceError("fixture chapter request blocks must be a non-empty array")
    required = request.get("required_block_ids")
    if not isinstance(required, list) or not required:
        raise PersistenceError(
            "fixture chapter request required_block_ids must be a non-empty array"
        )

    expected_fingerprint = spec.get("request_fingerprint")
    if expected_fingerprint is not None:
        actual = _chapter_request_fingerprint(request)
        if actual is None:
            raise PersistenceError(
                "fixture chapter records a request_fingerprint that cannot "
                "be verified here (chapter_contract unavailable); refusing "
                "to emit an unaudited candidate"
            )
        if actual != expected_fingerprint:
            raise PersistenceError(
                "fixture chapter request_fingerprint mismatch; refusing to emit "
                "a candidate for a different request"
            )

    entity_specs = spec["entities"]
    entities: list[dict[str, Any]] = []
    for position, entity_spec in enumerate(entity_specs):
        mention = str(entity_spec["mention"])
        if mention not in text:
            raise PersistenceError(
                f"fixture chapter entity mention {mention!r} "
                "is not present in the chapter text"
            )
        entities.append(
            {
                "temp_id": f"ent_{position + 1:03d}",
                "kind": "entity",
                "type": entity_spec["type"],
                "canonical_name": str(entity_spec["name"]),
                "aliases": [],
                "mentions": [
                    {"text": mention, "contextual": mention in _CONTEXTUAL_ONLY_SURFACES}
                ],
                "resolution": {"status": "unresolved"},
                "extraction": _chapter_meta(),
            }
        )
    entity_refs = [entity["temp_id"] for entity in entities]
    places = [
        entity["temp_id"] for entity in entities if entity["type"] == "place"
    ]
    event_spec = spec["event"]
    events = [
        {
            "temp_id": "evt_001",
            "kind": "event",
            "type": event_spec["type"],
            "title": str(event_spec["title"]),
            "time": None,
            "participants": [
                {"entity_ref": ref, "role": "subject" if index == 0 else "related"}
                for index, ref in enumerate(entity_refs)
            ],
            "places": places,
            "extraction": _chapter_meta(),
        }
    ]

    first_mention = str(entity_specs[0]["mention"])
    claims = [
        {
            "temp_id": "clm_001",
            "kind": "claim",
            "subject": {"kind": "entity", "ref": entity_refs[0]},
            "predicate": str(spec.get("predicate", "affected")),
            "object": None,
            "evidence": {
                "text": first_mention,
                "source_ref": "src_001",
                "locator": {"section": str(required[0])},
            },
            "assessment": {"status": "unassessed"},
            "extraction": _chapter_meta(),
        }
    ]

    translation_text = str(spec["translation_text"])
    translation = {
        "language": "zh-CN",
        "blocks": [
            {
                "block_id": "t_001",
                "text": translation_text,
                "source_block_ids": [str(block_id) for block_id in required],
                "entity_refs": [
                    {"kind": "entity", "ref": ref} for ref in entity_refs
                ],
                "event_refs": [{"kind": "event", "ref": "evt_001"}],
            }
        ],
    }

    mentions: list[dict[str, Any]] = []
    for position, entity_spec in enumerate(entity_specs):
        mention = str(entity_spec["mention"])
        contextual = mention in _CONTEXTUAL_ONLY_SURFACES
        selection = _chapter_selection_for(
            quote=mention, text=text, blocks=blocks, owner=f"mention m_{position + 1:03d}"
        )
        mentions.append(
            {
                "mention_id": f"m_{position + 1:03d}",
                "surface": mention,
                "contextual": contextual,
                "status": "unresolved" if contextual else "resolved",
                "target_ref": None if contextual else entity_refs[position],
                "candidate_refs": [],
                "selection": selection,
            }
        )

    record_sources: list[dict[str, Any]] = []
    for ref, kind in (
        [(ref, "entity") for ref in entity_refs]
        + [("evt_001", "event"), ("clm_001", "claim")]
    ):
        if kind == "claim":
            quote = first_mention
        elif kind == "event":
            quote = first_mention
        else:
            quote = str(entity_specs[entity_refs.index(ref)]["mention"])
        record_sources.append(
            {
                "record_ref": ref,
                "record_kind": kind,
                "selections": [
                    _chapter_selection_for(
                        quote=quote, text=text, blocks=blocks, owner=f"record {ref!r}"
                    )
                ],
            }
        )

    return {
        "schema": "chronicle.chapter-candidate",
        "version": "0.1",
        "chapter_id": chapter_id,
        "bundle": {
            "schema_version": "0.1",
            "source": {
                "temp_id": "src_001",
                "kind": "source",
                "source_type": "book",
                "title": str(spec["source_title"]),
                "language": "lzh",
                "extraction": _chapter_meta(),
            },
            "entities": entities,
            "events": events,
            "claims": claims,
            "warnings": [],
        },
        "translation": translation,
        "mentions": mentions,
        "record_sources": record_sources,
        "warnings": [],
    }


def _reading_block_for(
    base: dict[str, Any], request: dict[str, Any]
) -> dict[str, Any]:
    """Build the 0.2 ``reading`` block over a fixture 0.1 base candidate.

    Every unit is grounded in the request text and the base candidate's own
    temp refs: narrative time, current events, (empty) event spans and
    context entities. Coordinates/IDs stay program-computed, so the model
    never writes them. The result is meant for the T01 reading validator.
    """
    text = _require_text(request.get("normalized_text"), "fixture reading chapter text")
    blocks = request.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise PersistenceError("fixture reading chapter request blocks must be non-empty")
    bundle = base["bundle"]
    events = bundle.get("events") or []
    if len(events) != 1:
        raise PersistenceError(
            "fixture reading candidate requires exactly one bundle event"
        )
    event = events[0]
    event_id = event["temp_id"]
    participants = event.get("participants") or []
    participant_index = {
        participant.get("entity_ref"): index
        for index, participant in enumerate(participants)
        if isinstance(participant, dict)
    }
    entity_mentions = {
        entity["temp_id"]: str(entity["mentions"][0]["text"])
        for entity in bundle.get("entities") or []
        if isinstance(entity, dict) and entity.get("mentions")
    }
    entity_refs = [entity["temp_id"] for entity in bundle.get("entities") or []]

    units: list[dict[str, Any]] = []
    for translation_block in base["translation"]["blocks"]:
        block_event_refs = {
            ref.get("ref")
            for ref in translation_block.get("event_refs") or []
            if isinstance(ref, dict)
        }
        has_event = event_id in block_event_refs
        time_selection = _chapter_selection_for(
            quote=entity_mentions[entity_refs[0]],
            text=text,
            blocks=blocks,
            owner="fixture reading narrative_time",
        )
        context_entities: list[dict[str, Any]] = []
        for position, entity_ref in enumerate(entity_refs):
            roles: list[dict[str, Any]] = []
            if has_event and entity_ref in participant_index:
                roles.append(
                    {
                        "event_ref": event_id,
                        "participant_index": participant_index[entity_ref],
                    }
                )
            context_entities.append(
                {
                    "entity_ref": entity_ref,
                    "importance": "primary" if position == 0 else "other",
                    "source_selections": [
                        _chapter_selection_for(
                            quote=entity_mentions[entity_ref],
                            text=text,
                            blocks=blocks,
                            owner=f"fixture reading context {entity_ref!r}",
                        )
                    ],
                    "event_roles": roles,
                }
            )
        if has_event:
            narrative_time = {
                "mode": "events",
                "event_refs": [event_id],
                "from_block_id": None,
                "source_selections": [time_selection],
            }
            current_event_refs = [event_id]
        else:
            narrative_time = {
                "mode": "unknown",
                "event_refs": [],
                "from_block_id": None,
                "source_selections": [],
            }
            current_event_refs = []
            context_entities = []
        units.append(
            {
                "block_id": translation_block["block_id"],
                "narrative_time": narrative_time,
                "current_event_refs": current_event_refs,
                "event_spans": [],
                "context_entities": context_entities,
            }
        )
    return {"units": units, "warnings": []}


def build_reading_chapter_candidate(
    request: dict[str, Any], spec: dict[str, Any]
) -> dict[str, Any]:
    """Build a deterministic 0.2 reading candidate for one fixture chapter.

    Reuses the frozen 0.1 builder for the joint product and adds the reading
    annotation block, so the first-round sub-document and the second-round
    annotations are generated together from one whole-chapter request.
    """
    base = build_chapter_candidate(request, spec)
    base["version"] = "0.2"
    base["reading"] = _reading_block_for(base, request)
    return base


def _person_state_block_for(
    base: dict[str, Any], request: dict[str, Any]
) -> dict[str, Any]:
    """Build a deterministic 0.3 ``person_states`` block over a reading candidate.

    Source-grounded and shape-valid for any chapter fixture pack: one phase
    grounded on the first person entity's verbatim mention (when a person
    exists), one unit-phase binding per translation block in order, and one
    ``attest`` affiliation fact (with a supporting continuity) when a
    non-place target entity exists. When the pack has no person entity the
    block is a valid empty state with ``unknown`` unit bindings rather than a
    fabricated identity. Coordinates/IDs stay program-computed; the result is
    meant for the T01 ``person_state_contract`` validator.
    """
    text = _require_text(
        request.get("normalized_text"), "fixture person-state chapter text"
    )
    blocks = request.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise PersistenceError(
            "fixture person-state chapter request blocks must be non-empty"
        )
    bundle = base["bundle"]
    entities = [entity for entity in bundle.get("entities") or [] if isinstance(entity, dict)]
    persons = [entity for entity in entities if entity.get("type") == "person"]
    mentions = {
        entity["temp_id"]: str(entity["mentions"][0]["text"])
        for entity in entities
        if entity.get("mentions")
    }
    translation_blocks = base["translation"]["blocks"]

    phases: list[dict[str, Any]] = []
    unit_phases: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    continuities: list[dict[str, Any]] = []

    phase_selection: dict[str, Any] | None = None
    if persons:
        subject_ref = persons[0]["temp_id"]
        subject_mention = mentions.get(subject_ref)
        if not subject_mention:
            raise PersistenceError("fixture person-state subject has no mention")
        phase_selection = _chapter_selection_for(
            quote=subject_mention,
            text=text,
            blocks=blocks,
            owner="fixture person-state phase",
        )
        label = str(bundle["source"]["title"]).strip()[:120] or "章内階段"
        phases.append(
            {
                "phase_id": "ph_001",
                "label": label,
                "event_refs": [{"kind": "event", "ref": "evt_001"}],
                "source_selections": [phase_selection],
            }
        )
        target = next(
            (
                entity
                for entity in entities
                if entity.get("type") in ("polity", "organization")
                and entity["temp_id"] != subject_ref
            ),
            None,
        )
        if target is None:
            target = next(
                (
                    entity
                    for entity in entities
                    if entity.get("type") == "person" and entity["temp_id"] != subject_ref
                ),
                None,
            )
        if target is not None:
            facts.append(
                {
                    "fact_id": "pf_001",
                    "person_ref": {"kind": "entity", "ref": subject_ref},
                    "dimension": "affiliation",
                    "value_ref": None,
                    "relation": "serves",
                    "target_ref": {"kind": "entity", "ref": target["temp_id"]},
                    "operation": "attest",
                    "qualification": "ordinary",
                    "phase_ref": "ph_001",
                    "claim_refs": [],
                    "source_selections": [phase_selection],
                    "attribution": "narrator",
                }
            )
            continuities.append(
                {
                    "assertion_id": "pc_001",
                    "fact_ref": "pf_001",
                    "start_phase_ref": "ph_001",
                    "end_phase_ref": None,
                    "source_selections": [phase_selection],
                }
            )

    for translation_block in translation_blocks:
        event_refs = {
            ref.get("ref")
            for ref in translation_block.get("event_refs") or []
            if isinstance(ref, dict)
        }
        if phase_selection is not None and "evt_001" in event_refs:
            unit_phases.append(
                {
                    "block_id": translation_block["block_id"],
                    "mode": "single",
                    "phase_refs": ["ph_001"],
                    "source_selections": [phase_selection],
                }
            )
        else:
            unit_phases.append(
                {
                    "block_id": translation_block["block_id"],
                    "mode": "unknown",
                    "phase_refs": [],
                    "source_selections": [],
                }
            )
    return {
        "phases": phases,
        "phase_orders": [],
        "unit_phases": unit_phases,
        "facts": facts,
        "continuities": continuities,
        "disagreements": [],
    }


def build_person_state_chapter_candidate(
    request: dict[str, Any], spec: dict[str, Any]
) -> dict[str, Any]:
    """Build a deterministic 0.3 person-state candidate for one fixture chapter.

    Reuses the frozen 0.2 reading candidate and adds the third-round
    ``person_states`` block, so translation, C0 records, reading annotations
    and person-state facts are generated together from one whole-chapter
    request.
    """
    base = build_reading_chapter_candidate(request, spec)
    base["version"] = "0.3"
    base["person_states"] = _person_state_block_for(base, request)
    return base


def _chapter_header_lines(prompt: str, marker: str, description: str) -> str:
    """Return the JSON paragraph following a production prompt marker."""
    start = prompt.find(marker)
    if start < 0:
        raise PersistenceError(
            f"fixture chapter prompt is missing {description}"
        )
    rest = prompt[start + len(marker):]
    lines: list[str] = []
    for line in rest.splitlines():
        if not line.strip():
            break
        lines.append(line)
    if not lines:
        raise PersistenceError(
            f"fixture chapter prompt carries no {description} JSON"
        )
    return "\n".join(lines)


def _chapter_request_from_t05_prompt(prompt: str) -> dict[str, Any]:
    """Rebuild the program-owned chapter request from a T05 prompt.

    Parses only the renderer's exact machine-readable sections — the
    ``CHAPTER REQUEST`` header JSON, the ``REQUIRED BLOCKS`` JSON
    array, the ``CHAPTER BLOCKS`` ranges, and the verbatim
    ``FULL CHAPTER TEXT`` — and re-verifies every binding (text hash,
    block ranges, required coverage) fail-closed. The rebuilt request
    is byte-equivalent to the program-owned one for candidate
    construction; unknown layouts are refused, never guessed.
    """
    try:
        header = json.loads(
            _chapter_header_lines(
                prompt, _CHAPTER_T05_HEADER_MARKER, "CHAPTER REQUEST header"
            )
        )
    except json.JSONDecodeError as exc:
        raise PersistenceError(
            "fixture chapter CHAPTER REQUEST header is invalid JSON"
        ) from exc
    if not isinstance(header, dict):
        raise PersistenceError("fixture chapter CHAPTER REQUEST header must be an object")
    for key in (
        "chapter_id", "revision_id", "source_sha256",
        "normalized_sha256", "limits",
    ):
        if header.get(key) in (None, ""):
            raise PersistenceError(
                f"fixture chapter CHAPTER REQUEST header is missing {key!r}"
            )
    required_at = prompt.find(_CHAPTER_T05_REQUIRED_MARKER)
    if required_at < 0:
        raise PersistenceError(
            "fixture chapter prompt is missing REQUIRED BLOCKS"
        )
    try:
        required = json.loads(
            _chapter_header_lines(
                prompt[required_at:], _CHAPTER_T05_REQUIRED_MARKER,
                "REQUIRED BLOCKS",
            )
        )
    except json.JSONDecodeError as exc:
        raise PersistenceError(
            "fixture chapter REQUIRED BLOCKS is invalid JSON"
        ) from exc
    if (
        not isinstance(required, list)
        or not required
        or any(not isinstance(item, str) or not item for item in required)
    ):
        raise PersistenceError(
            "fixture chapter REQUIRED BLOCKS must be a non-empty string array"
        )
    text = _between(
        prompt, _CHAPTER_T05_TEXT_START, _CHAPTER_T05_TEXT_END, "CHAPTER SOURCE TEXT"
    )
    if not text:
        raise PersistenceError("fixture chapter FULL CHAPTER TEXT is empty")
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != header["normalized_sha256"]:
        raise PersistenceError(
            "fixture chapter FULL CHAPTER TEXT does not match the "
            "CHAPTER REQUEST hash; refusing a drifted reconstruction"
        )
    blocks_at = prompt.find(_CHAPTER_T05_BLOCKS_MARKER)
    text_at = prompt.find(_CHAPTER_T05_TEXT_MARKER)
    if blocks_at < 0 or text_at < 0 or text_at < blocks_at:
        raise PersistenceError(
            "fixture chapter prompt is missing CHAPTER BLOCKS coverage"
        )
    section = prompt[blocks_at:text_at]
    blocks: list[dict[str, Any]] = []
    for match in _CHAPTER_T05_BLOCK_RE.finditer(section):
        start, end = int(match.group("start")), int(match.group("end"))
        content = match.group("content")
        if not (0 <= start < end <= len(text)) or text[start:end] != content:
            raise PersistenceError(
                f"fixture chapter block {match.group('block_id')!r} range "
                f"[{start},{end}) does not match the chapter text; "
                "refusing a drifted reconstruction"
            )
        blocks.append(
            {
                "block_id": match.group("block_id"),
                "kind": match.group("kind"),
                "start": start,
                "end": end,
                "content_sha256": hashlib.sha256(
                    content.encode("utf-8")
                ).hexdigest(),
            }
        )
    if not blocks:
        raise PersistenceError("fixture chapter CHAPTER BLOCKS carries no blocks")
    covered = {block["block_id"] for block in blocks}
    missing = [item for item in required if item not in covered]
    if missing:
        raise PersistenceError(
            f"fixture chapter REQUIRED BLOCKS {missing} are not rendered "
            "in CHAPTER BLOCKS; refusing a partial reconstruction"
        )
    return {
        "chapter_id": header["chapter_id"],
        "chapter_index": header.get("chapter_index"),
        "title": header.get("title"),
        "revision_id": header["revision_id"],
        "document_id": header.get("document_id"),
        "source_sha256": header["source_sha256"],
        "normalized_sha256": header["normalized_sha256"],
        "normalized_text": text,
        "blocks": blocks,
        "required_block_ids": list(required),
        "plan_version": header.get("plan_version"),
        "limits": header["limits"],
        "schema_versions": header.get("schema_versions"),
    }


@dataclass(frozen=True)
class FixtureChapterModel:
    """Deterministic joint chapter-candidate provider for development."""

    name: str
    chapters: tuple[dict[str, Any], ...]

    def chapter_ids(self) -> list[str]:
        return [str(spec["chapter_id"]) for spec in self.chapters]

    def spec_for(self, chapter_id: str) -> dict[str, Any]:
        for spec in self.chapters:
            if spec.get("chapter_id") == chapter_id:
                return spec
        raise PersistenceError(
            f"fixture chapter pack has no chapter {chapter_id!r}; "
            "refusing to invent history for an unknown chapter"
        )

    def build_for_request(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise PersistenceError("fixture chapter request must be an object")
        chapter_id = request.get("chapter_id")
        if not isinstance(chapter_id, str) or not chapter_id:
            raise PersistenceError("fixture chapter request requires chapter_id")
        return build_chapter_candidate(request, self.spec_for(chapter_id))

    def complete(self, prompt: str) -> str:
        if not isinstance(prompt, str) or not prompt:
            raise PersistenceError("fixture chapter prompt must be non-empty text")
        if (
            CHAPTER_REQUEST_START in prompt
            and CHAPTER_REQUEST_END in prompt
        ):
            raw = _between(
                prompt,
                CHAPTER_REQUEST_START.strip(),
                CHAPTER_REQUEST_END.strip(),
                "CHAPTER_REQUEST",
            )
            try:
                request = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise PersistenceError(
                    "fixture chapter CHAPTER_REQUEST is invalid JSON"
                ) from exc
            if not isinstance(request, dict):
                raise PersistenceError(
                    "fixture chapter CHAPTER_REQUEST must be an object"
                )
        elif _CHAPTER_T05_HEADER_MARKER in prompt:
            # Production T05 envelope: rebuild the exact program-owned
            # request from the renderer's machine-readable sections
            # (header, required blocks, block ranges, verbatim chapter
            # text), verified fail-closed. Anything else is refused.
            request = _chapter_request_from_t05_prompt(prompt)
        else:
            found = _CHAPTER_ID_PATTERN.search(prompt)
            hint = f" (saw chapter {found.group(0)!r})" if found else ""
            raise PersistenceError(
                "fixture chapter prompt is missing the CHAPTER_REQUEST envelope "
                "and carries no T05 CHAPTER REQUEST header"
                f"{hint}; refusing to guess the chapter request"
            )
        candidate = self.build_for_request(request)
        return json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))


def models_from_chapter_fixture_pack(
    path: Path | str,
) -> FixtureChapterModel:
    """Load one explicit development chapter fixture pack."""
    payload = _load_chapter_pack(path)
    version = _require_text(payload.get("model_version"), "chapter fixture model_version")
    return FixtureChapterModel(
        name=f"fixture:{version}:{CHAPTER_MODEL_SUFFIX}",
        chapters=tuple(payload["chapters"]),
    )


#: Suffix distinguishing the 0.2 reading fixture provider name from 0.1.
READING_CHAPTER_MODEL_SUFFIX = "reading-chapter"


@dataclass(frozen=True)
class FixtureReadingChapterModel(FixtureChapterModel):
    """Deterministic 0.2 joint + reading-candidate provider.

    Same request parsing and fail-closed chapter binding as the 0.1 fixture,
    but each chapter emits ``chronicle.chapter-candidate / 0.2`` with a
    reading annotation block over the whole chapter. Acceptance runs the T01
    ``reading_contract`` validator, never a weaker parallel check.
    """

    def build_for_request(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise PersistenceError("fixture reading chapter request must be an object")
        chapter_id = request.get("chapter_id")
        if not isinstance(chapter_id, str) or not chapter_id:
            raise PersistenceError("fixture reading chapter request requires chapter_id")
        return build_reading_chapter_candidate(request, self.spec_for(chapter_id))


def models_from_reading_chapter_fixture_pack(
    path: Path | str,
) -> FixtureReadingChapterModel:
    """Load one explicit development 0.2 reading chapter fixture pack."""
    payload = _load_chapter_pack(path)
    version = _require_text(payload.get("model_version"), "chapter fixture model_version")
    return FixtureReadingChapterModel(
        name=f"fixture:{version}:{READING_CHAPTER_MODEL_SUFFIX}",
        chapters=tuple(payload["chapters"]),
    )


#: Suffix distinguishing the 0.3 person-state fixture provider name.
PERSON_STATE_CHAPTER_MODEL_SUFFIX = "person-state-chapter"


@dataclass(frozen=True)
class FixturePersonStateChapterModel(FixtureReadingChapterModel):
    """Deterministic 0.3 joint + reading + person-state candidate provider.

    Same request parsing and fail-closed chapter binding as the 0.2 fixture,
    but each chapter emits ``chronicle.chapter-candidate / 0.3`` with a
    person_states block over the whole chapter. Acceptance runs the T01
    ``person_state_contract`` validator, never a weaker parallel check.
    """

    #: Explicit version so version-selection wiring can bind 0.3 without
    #: re-deriving it from the provider name.
    candidate_version = "0.3"

    def build_for_request(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise PersistenceError("fixture person-state chapter request must be an object")
        chapter_id = request.get("chapter_id")
        if not isinstance(chapter_id, str) or not chapter_id:
            raise PersistenceError(
                "fixture person-state chapter request requires chapter_id"
            )
        return build_person_state_chapter_candidate(request, self.spec_for(chapter_id))


def models_from_person_state_chapter_fixture_pack(
    path: Path | str,
) -> FixturePersonStateChapterModel:
    """Load one explicit development 0.3 person-state chapter fixture pack."""
    payload = _load_chapter_pack(path)
    version = _require_text(payload.get("model_version"), "chapter fixture model_version")
    return FixturePersonStateChapterModel(
        name=f"fixture:{version}:{PERSON_STATE_CHAPTER_MODEL_SUFFIX}",
        chapters=tuple(payload["chapters"]),
    )
