"""Structured-output projection for Chronicle extraction models.

This is deliberately NOT a second Chronicle acceptance schema.  It is a strict
Responses JSON-Schema projection containing only shapes that are already valid
under ``ingestion/schemas/chronicle-v0.1.schema.json``.  The canonical schema
and the mechanical grounding/reference/time validators remain the acceptance
authority after generation.

Why a projection exists: the provider's ``strict=true`` JSON-Schema subset does
not accept the canonical contract's composition-heavy ``allOf``/``oneOf``
identity model.  Restricting generation to temp-id, model-extraction records is
safe for the chunk stage and prevents format drift without weakening the
canonical validator.
"""

from __future__ import annotations

from typing import Any

FORMAT_NAME = "chronicle_extraction_bundle"


def _extraction() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["method"],
        "properties": {"method": {"type": "string", "const": "model"}},
    }


def _reference() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "ref"],
        "properties": {
            "kind": {"type": "string", "enum": ["entity_ref", "event_ref"]},
            "ref": {"type": "string", "minLength": 1},
        },
    }


def _literal() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "value"],
        "properties": {
            "kind": {"type": "string", "const": "literal"},
            "value": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "number"},
                    {"type": "boolean"},
                    {"type": "null"},
                ]
            },
        },
    }


def _source_calendar() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["system", "inherited_fields"],
        "properties": {
            "system": {
                "type": "string",
                "enum": [
                    "chinese_lunisolar_regnal",
                    "proleptic_gregorian",
                    "unknown",
                ],
            },
            "inherited_fields": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["era", "era_year", "season", "month", "day"],
                },
            },
        },
    }


def _normalized_time() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["calendar", "year", "precision", "conversion_status"],
        "properties": {
            "calendar": {"type": "string", "const": "proleptic_gregorian"},
            "year": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "precision": {
                "type": "string",
                "enum": ["day", "month", "year", "range", "unknown"],
            },
            "conversion_status": {
                "type": "string",
                "enum": ["exact", "year_only", "partial", "unresolved"],
            },
        },
    }


def _time() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["original_text", "source_calendar", "normalized"],
        "properties": {
            "original_text": {"type": "string", "minLength": 1},
            "source_calendar": _source_calendar(),
            "normalized": {
                "anyOf": [{"type": "null"}, _normalized_time()],
            },
        },
    }


def _nullable_time() -> dict[str, Any]:
    return {"anyOf": [{"type": "null"}, _time()]}


def extraction_model_schema() -> dict[str, Any]:
    """Return the strict model-generation subset of canonical bundle v0.1."""

    mention = {
        "type": "object",
        "additionalProperties": False,
        "required": ["text"],
        "properties": {"text": {"type": "string", "minLength": 1}},
    }
    # Chunk extraction never owns entity identity decisions.  Keep every
    # model-produced Entity unresolved and express ambiguity through warnings;
    # the later deterministic resolution/review stage is the only place that
    # may classify/link identities.  This also matches assembly's strict
    # temp-ID-only input contract.
    resolution = {
        "type": "object",
        "additionalProperties": False,
        "required": ["status"],
        "properties": {
            "status": {
                "type": "string",
                "const": "unresolved",
            }
        },
    }
    participant = {
        "type": "object",
        "additionalProperties": False,
        "required": ["entity_ref", "role"],
        "properties": {
            "entity_ref": {"type": "string", "pattern": "^ent_[0-9]{3,}$"},
            "role": {"type": "string", "minLength": 1},
        },
    }
    source = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "temp_id",
            "kind",
            "source_type",
            "title",
            "language",
            "extraction",
        ],
        "properties": {
            "temp_id": {"type": "string", "pattern": "^src_[0-9]{3,}$"},
            "kind": {"type": "string", "const": "source"},
            "source_type": {
                "type": "string",
                "enum": ["book", "article", "web", "dataset", "manuscript", "other"],
            },
            "title": {"type": "string", "minLength": 1},
            "language": {"type": "string", "minLength": 1},
            "extraction": _extraction(),
        },
    }
    entity = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "temp_id",
            "kind",
            "type",
            "canonical_name",
            "aliases",
            "mentions",
            "resolution",
            "extraction",
        ],
        "properties": {
            "temp_id": {"type": "string", "pattern": "^ent_[0-9]{3,}$"},
            "kind": {"type": "string", "const": "entity"},
            "type": {
                "type": "string",
                "enum": [
                    "person",
                    "place",
                    "polity",
                    "organization",
                    "army",
                    "office",
                    "group",
                    "other",
                ],
            },
            "canonical_name": {"type": "string", "minLength": 1},
            "aliases": {"type": "array", "items": {"type": "string"}},
            "mentions": {"type": "array", "items": mention},
            "resolution": resolution,
            "extraction": _extraction(),
        },
    }
    event = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "temp_id",
            "kind",
            "type",
            "title",
            "time",
            "participants",
            "places",
            "extraction",
        ],
        "properties": {
            "temp_id": {"type": "string", "pattern": "^evt_[0-9]{3,}$"},
            "kind": {"type": "string", "const": "event"},
            "type": {
                "type": "string",
                "enum": [
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
                ],
            },
            "title": {"type": "string", "minLength": 1},
            "time": _nullable_time(),
            "participants": {"type": "array", "items": participant},
            "places": {
                "type": "array",
                "items": {"type": "string", "pattern": "^ent_[0-9]{3,}$"},
            },
            "extraction": _extraction(),
        },
    }
    evidence = {
        "type": "object",
        "additionalProperties": False,
        "required": ["text", "source_ref", "locator"],
        "properties": {
            "text": {"type": "string", "minLength": 1},
            "source_ref": {"type": "string", "pattern": "^src_[0-9]{3,}$"},
            "locator": {
                "type": "object",
                "additionalProperties": False,
                "required": ["section"],
                "properties": {"section": {"type": "string", "minLength": 1}},
            },
        },
    }
    assessment = {
        "type": "object",
        "additionalProperties": False,
        "required": ["status"],
        "properties": {"status": {"type": "string", "const": "unassessed"}},
    }
    claim = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "temp_id",
            "kind",
            "subject",
            "predicate",
            "object",
            "evidence",
            "assessment",
            "extraction",
        ],
        "properties": {
            "temp_id": {"type": "string", "pattern": "^clm_[0-9]{3,}$"},
            "kind": {"type": "string", "const": "claim"},
            "subject": _reference(),
            "predicate": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
            "object": {
                "anyOf": [{"type": "null"}, _reference(), _literal()],
            },
            "evidence": evidence,
            "assessment": assessment,
            "extraction": _extraction(),
        },
    }
    warning = {
        "type": "object",
        "additionalProperties": False,
        "required": ["type", "severity", "message"],
        "properties": {
            "type": {"type": "string", "minLength": 1},
            "severity": {
                "type": "string",
                "enum": ["info", "warning", "error"],
            },
            "message": {"type": "string", "minLength": 1},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "source", "entities", "events", "claims", "warnings"],
        "properties": {
            "schema_version": {"type": "string", "const": "0.1"},
            "source": source,
            "entities": {"type": "array", "items": entity},
            "events": {"type": "array", "items": event},
            "claims": {"type": "array", "items": claim},
            "warnings": {"type": "array", "items": warning},
        },
    }


def extraction_text_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": FORMAT_NAME,
        "schema": extraction_model_schema(),
        "strict": True,
    }


# ---------------------------------------------------------------------------
# Chapter candidate projection (C2-R1-T06)
# ---------------------------------------------------------------------------
# Strict Responses projection of ``chronicle.chapter-candidate / 0.1``
# (T01 canonical schema). It contains only model-generatable fields: every
# program-bound value (hashes, offsets, anchor IDs, canonical IDs, request
# fingerprints, producing runs) is absent by construction. Local acceptance
# still calls the T01 canonical validator (``chapter_contract.
# validate_chapter_candidate``); this projection only constrains generation.
#
# Like the chunk projection above, the canonical contract's ``allOf``/
# ``oneOf``/``$ref`` composition is flattened into plain objects so the
# provider's ``strict=true`` subset accepts the format. ``anyOf`` is used
# only for explicitly nullable scalar/object slots, matching the existing
# projection idiom in this file.

CHAPTER_CANDIDATE_FORMAT_NAME = "chronicle_chapter_candidate"


def _chapter_nullable_string() -> dict[str, Any]:
    return {"anyOf": [{"type": "string"}, {"type": "null"}]}


def _chapter_nullable_number() -> dict[str, Any]:
    return {"anyOf": [{"type": "number"}, {"type": "null"}]}


def _chapter_extraction_meta() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["method", "job_id", "confidence"],
        "properties": {
            "method": {"type": "string", "enum": ["human_gold", "model", "parser"]},
            "job_id": _chapter_nullable_string(),
            "confidence": _chapter_nullable_number(),
        },
    }


def _chapter_typed_ref() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "ref"],
        "properties": {
            "kind": {"type": "string", "enum": ["entity", "event"]},
            "ref": {"type": "string", "minLength": 1},
        },
    }


def _chapter_literal() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "value"],
        "properties": {
            "kind": {"type": "string", "const": "literal"},
            "value": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "number"},
                    {"type": "boolean"},
                    {"type": "null"},
                ]
            },
        },
    }


def _chapter_time() -> dict[str, Any]:
    # Minimal generation shape: the model states the original text and the
    # source calendar system plus inherited fields. Era/year/month/day
    # normalization is program-checked by the T01 time-precision validator;
    # the projection withholds month/day slots so they cannot be invented.
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["original_text", "source_calendar", "normalized"],
        "properties": {
            "original_text": {"type": "string", "minLength": 1},
            "source_calendar": {
                "type": "object",
                "additionalProperties": False,
                "required": ["system", "inherited_fields"],
                "properties": {
                    "system": {
                        "type": "string",
                        "enum": [
                            "chinese_lunisolar_regnal",
                            "proleptic_gregorian",
                            "unknown",
                        ],
                    },
                    "inherited_fields": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["era", "era_year", "season", "month", "day"],
                        },
                    },
                },
            },
            "normalized": {
                "anyOf": [
                    {"type": "null"},
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "calendar",
                            "year",
                            "precision",
                            "conversion_status",
                        ],
                        "properties": {
                            "calendar": {
                                "type": "string",
                                "const": "proleptic_gregorian",
                            },
                            "year": {
                                "anyOf": [{"type": "integer"}, {"type": "null"}]
                            },
                            "precision": {
                                "type": "string",
                                "enum": ["day", "month", "year", "range", "unknown"],
                            },
                            "conversion_status": {
                                "type": "string",
                                "enum": ["exact", "year_only", "partial", "unresolved"],
                            },
                        },
                    },
                ]
            },
        },
    }


def _chapter_selection() -> dict[str, Any]:
    # The model names block endpoints and quotes verbatim text; offsets and
    # occurrence enumeration stay program-computed (T01 resolve_selection).
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["first_block_id", "last_block_id", "quote", "occurrence"],
        "properties": {
            "first_block_id": {"type": "string", "minLength": 1},
            "last_block_id": {"type": "string", "minLength": 1},
            "quote": {"type": "string", "minLength": 1},
            "occurrence": {"type": "integer", "minimum": 1},
        },
    }


def chapter_candidate_model_schema() -> dict[str, Any]:
    """Return the strict model-generation subset of chapter-candidate 0.1."""
    entity_mention = {
        "type": "object",
        "additionalProperties": False,
        "required": ["text", "contextual"],
        "properties": {
            "text": {"type": "string", "minLength": 1},
            "contextual": {"type": "boolean"},
        },
    }
    source = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "temp_id",
            "kind",
            "source_type",
            "title",
            "language",
            "extraction",
        ],
        "properties": {
            "temp_id": {"type": "string", "pattern": "^src_[0-9]{3,}$"},
            "kind": {"type": "string", "const": "source"},
            "source_type": {
                "type": "string",
                "enum": ["book", "article", "web", "dataset", "manuscript", "other"],
            },
            "title": {"type": "string", "minLength": 1},
            "language": {"type": "string", "minLength": 1},
            "extraction": _chapter_extraction_meta(),
        },
    }
    entity = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "temp_id",
            "kind",
            "type",
            "canonical_name",
            "aliases",
            "mentions",
            "resolution",
            "extraction",
        ],
        "properties": {
            "temp_id": {"type": "string", "pattern": "^ent_[0-9]{3,}$"},
            "kind": {"type": "string", "const": "entity"},
            "type": {
                "type": "string",
                "enum": [
                    "person",
                    "place",
                    "polity",
                    "organization",
                    "army",
                    "office",
                    "group",
                    "other",
                ],
            },
            "canonical_name": {"type": "string", "minLength": 1},
            "aliases": {"type": "array", "items": {"type": "string"}},
            "mentions": {"type": "array", "items": entity_mention},
            "resolution": {
                "type": "object",
                "additionalProperties": False,
                "required": ["status"],
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["unresolved", "new", "ambiguous"],
                    }
                },
            },
            "extraction": _chapter_extraction_meta(),
        },
    }
    participant = {
        "type": "object",
        "additionalProperties": False,
        "required": ["entity_ref", "role"],
        "properties": {
            "entity_ref": {"type": "string", "minLength": 1},
            "role": {"type": "string", "minLength": 1},
        },
    }
    event = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "temp_id",
            "kind",
            "type",
            "title",
            "time",
            "participants",
            "places",
            "extraction",
        ],
        "properties": {
            "temp_id": {"type": "string", "pattern": "^evt_[0-9]{3,}$"},
            "kind": {"type": "string", "const": "event"},
            "type": {
                "type": "string",
                "enum": [
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
                ],
            },
            "title": {"type": "string", "minLength": 1},
            "time": {"anyOf": [{"type": "null"}, _chapter_time()]},
            "participants": {"type": "array", "items": participant},
            "places": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "extraction": _chapter_extraction_meta(),
        },
    }
    evidence = {
        "type": "object",
        "additionalProperties": False,
        "required": ["text", "source_ref", "locator"],
        "properties": {
            "text": {"type": "string", "minLength": 1},
            "source_ref": {"type": "string", "pattern": "^src_[0-9]{3,}$"},
            "locator": {
                "type": "object",
                "additionalProperties": False,
                "required": ["section"],
                "properties": {"section": {"type": "string", "minLength": 1}},
            },
        },
    }
    claim = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "temp_id",
            "kind",
            "subject",
            "predicate",
            "object",
            "evidence",
            "assessment",
            "extraction",
        ],
        "properties": {
            "temp_id": {"type": "string", "pattern": "^clm_[0-9]{3,}$"},
            "kind": {"type": "string", "const": "claim"},
            "subject": _chapter_typed_ref(),
            "predicate": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
            "object": {
                "anyOf": [{"type": "null"}, _chapter_typed_ref(), _chapter_literal()],
            },
            "evidence": evidence,
            "assessment": {
                "type": "object",
                "additionalProperties": False,
                "required": ["status"],
                "properties": {"status": {"type": "string", "const": "unassessed"}},
            },
            "extraction": _chapter_extraction_meta(),
        },
    }
    translation_block = {
        "type": "object",
        "additionalProperties": False,
        "required": ["block_id", "text", "source_block_ids", "entity_refs", "event_refs"],
        "properties": {
            "block_id": {"type": "string", "minLength": 1},
            "text": {"type": "string", "minLength": 1},
            "source_block_ids": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1,
            },
            "entity_refs": {"type": "array", "items": _chapter_typed_ref()},
            "event_refs": {"type": "array", "items": _chapter_typed_ref()},
        },
    }
    mention = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "mention_id",
            "surface",
            "contextual",
            "status",
            "target_ref",
            "candidate_refs",
            "selection",
        ],
        "properties": {
            "mention_id": {"type": "string", "pattern": "^m_[0-9]{3,}$"},
            "surface": {"type": "string", "minLength": 1},
            "contextual": {"type": "boolean"},
            "status": {
                "type": "string",
                "enum": ["resolved", "ambiguous", "unresolved"],
            },
            "target_ref": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "candidate_refs": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "selection": _chapter_selection(),
        },
    }
    record_source = {
        "type": "object",
        "additionalProperties": False,
        "required": ["record_ref", "record_kind", "selections"],
        "properties": {
            "record_ref": {"type": "string", "minLength": 1},
            "record_kind": {"type": "string", "enum": ["entity", "event", "claim"]},
            "selections": {
                "type": "array",
                "items": _chapter_selection(),
                "minItems": 1,
            },
        },
    }
    warning = {
        "type": "object",
        "additionalProperties": False,
        "required": ["type", "severity", "message", "refs"],
        "properties": {
            "type": {"type": "string", "minLength": 1},
            "severity": {
                "type": "string",
                "enum": ["info", "warning", "error"],
            },
            "message": {"type": "string", "minLength": 1},
            "refs": {"type": "array", "items": {"type": "string"}},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema",
            "version",
            "chapter_id",
            "bundle",
            "translation",
            "mentions",
            "record_sources",
            "warnings",
        ],
        "properties": {
            "schema": {"type": "string", "const": "chronicle.chapter-candidate"},
            "version": {"type": "string", "const": "0.1"},
            "chapter_id": {"type": "string", "pattern": "^ch_[0-9a-f]{24}$"},
            "bundle": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "schema_version",
                    "source",
                    "entities",
                    "events",
                    "claims",
                    "warnings",
                ],
                "properties": {
                    "schema_version": {"type": "string", "const": "0.1"},
                    "source": source,
                    "entities": {"type": "array", "items": entity},
                    "events": {"type": "array", "items": event},
                    "claims": {"type": "array", "items": claim},
                    "warnings": {"type": "array", "items": warning},
                },
            },
            "translation": {
                "type": "object",
                "additionalProperties": False,
                "required": ["language", "blocks"],
                "properties": {
                    "language": {"type": "string", "const": "zh-CN"},
                    "blocks": {
                        "type": "array",
                        "items": translation_block,
                        "minItems": 1,
                    },
                },
            },
            "mentions": {"type": "array", "items": mention},
            "record_sources": {"type": "array", "items": record_source},
            "warnings": {"type": "array", "items": warning},
        },
    }


def chapter_candidate_text_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": CHAPTER_CANDIDATE_FORMAT_NAME,
        "schema": chapter_candidate_model_schema(),
        "strict": True,
    }
