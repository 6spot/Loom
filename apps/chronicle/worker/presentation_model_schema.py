"""Responses generation constraint derived from the Reader candidate schema.

This is a provider adapter, not another presentation contract. Target equality,
Claim scope and uncertainty remain checked by persistence.presentation after
the call. The canonical candidate schema stays unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FORMAT_NAME = "chronicle_reader_presentation_v01"
CANONICAL_SCHEMA = (
    Path(__file__).resolve().parent.parent
    / "ingestion" / "schemas" / "chronicle-reader-presentation-v0.1.schema.json"
)


def presentation_model_schema() -> dict[str, Any]:
    """Adapt the canonical v0.1 schema to the strict Responses subset."""
    schema = json.loads(CANONICAL_SCHEMA.read_text(encoding="utf-8"))
    for annotation in ("$schema", "$id", "title"):
        schema.pop(annotation, None)

    def adapt(node: dict[str, Any]) -> None:
        # Canonical const/enum fields are all strings. Responses requires an
        # explicit type even where JSON Schema can infer it from const/enum.
        if "const" in node or "enum" in node:
            node.setdefault("type", "string")
        # uniqueItems is outside the documented strict array subset. Keep
        # min/maxItems; the prompt requires unique supports and the existing
        # validator normalizes duplicate refs before immutable persistence.
        node.pop("uniqueItems", None)
        for prop in node.get("properties", {}).values():
            adapt(prop)
        if isinstance(node.get("items"), dict):
            adapt(node["items"])

    adapt(schema)
    return schema


def presentation_text_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": FORMAT_NAME,
        "schema": presentation_model_schema(),
        "strict": True,
    }
