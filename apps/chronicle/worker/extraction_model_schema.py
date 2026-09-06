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
