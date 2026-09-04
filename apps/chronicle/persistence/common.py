"""Shared Chronicle PostgreSQL persistence helpers."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Iterable


class PersistenceError(RuntimeError):
    """Base error for Chronicle persistence failures."""


class PersistenceConflict(PersistenceError):
    """Raised when an immutable persisted key is presented with new content."""


class LeaseLost(PersistenceConflict):
    """Raised when a worker attempts a mutation without holding the job lease.

    A subclass of `PersistenceConflict` so HTTP/API layers keep mapping it
    to a 409-style conflict, while workers treat it as an explicit halt:
    the lease moved to another worker (or was cleared by cancellation) and
    the stale worker must stop writing immediately.
    """


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def record_ref(record: dict[str, Any]) -> str:
    value = record.get("temp_id") or record.get("id")
    if not isinstance(value, str) or not value:
        raise PersistenceError("staged record is missing temp_id/id")
    return value


def parse_uuid7(value: Any, description: str) -> uuid.UUID:
    if not isinstance(value, str):
        raise PersistenceError(f"{description} must be a UUID string")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise PersistenceError(f"{description} is not a valid UUID: {value!r}") from exc
    if parsed.version != 7:
        raise PersistenceError(f"{description} must be UUIDv7, got version {parsed.version}")
    return parsed


def require_object(value: Any, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PersistenceError(f"{description} must be a JSON object")
    return value


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersistenceError(f"failed to load {path}: {exc}") from exc
    return require_object(value, str(path))


def stable_relation_payload(relation: dict[str, Any]) -> dict[str, Any]:
    """Return semantic identity fields for one canonical event relation."""
    return {
        "type": relation.get("type"),
        "left_canonical_event_id": relation.get("left_canonical_event_id"),
        "right_canonical_event_id": relation.get("right_canonical_event_id"),
    }


def import_key(
    bundle_hashes: dict[str, str],
    resolution_hashes: Iterable[str],
    catalog_hash: str,
) -> str:
    return sha256_json(
        {
            "bundles": [
                {"label": label, "sha256": bundle_hashes[label]}
                for label in sorted(bundle_hashes)
            ],
            "resolutions": sorted(resolution_hashes),
            "catalog": catalog_hash,
        }
    )
