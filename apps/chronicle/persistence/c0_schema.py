"""Canonical C0 bundle schema loader shared by current projections."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from common import PersistenceError

CANONICAL_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "ingestion"
    / "schemas"
    / "chronicle-v0.1.schema.json"
)
CANONICAL_SCHEMA_ID = "https://loom.local/chronicle/schemas/chronicle-v0.1.schema.json"


@lru_cache(maxsize=1)
def canonical_schema() -> dict[str, Any]:
    """Load and identity-check the immutable C0 JSON Schema."""
    try:
        schema = json.loads(CANONICAL_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PersistenceError(
            f"canonical Chronicle schema is unreadable at {CANONICAL_SCHEMA_PATH}"
        ) from exc
    if not isinstance(schema, dict) or schema.get("$id") != CANONICAL_SCHEMA_ID:
        raise PersistenceError(
            "canonical Chronicle schema failed its identity check; refusing "
            "to validate against an unrecognized contract"
        )
    return schema


def require_canonical_schema(value: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve the canonical schema and reject caller-supplied alternatives."""
    schema = canonical_schema()
    if value is not None and value != schema:
        raise PersistenceError(
            "only the canonical Chronicle C0 schema is accepted"
        )
    return schema
