"""Pure 0.4 chapter contracts: source scope, validation and accepted products.

Source segmentation is deterministic bookkeeping for one complete chapter;
it never creates translation tasks. Frozen 0.3 validators own the unchanged
candidate sub-document. Only this generation excludes explicitly bracketed
annotations from required translation coverage and binds content acceptance.
"""

from __future__ import annotations

import copy
import re
from functools import lru_cache
from typing import Any

import chapter_contract as C
import person_state_contract as P
import reading_contract as R
from common import PersistenceError, sha256_json

CANDIDATE_SCHEMA = C.CANDIDATE_SCHEMA
CANDIDATE_VERSION = "0.4"
ARTIFACT_SCHEMA = C.ARTIFACT_SCHEMA
ARTIFACT_VERSION = "0.4"
SOURCE_SCOPE_SCHEMA = "chronicle.chapter-source-scope"
SOURCE_SCOPE_VERSION = "0.1"
ACCEPTANCE_SCHEMA = "chronicle.chapter-acceptance"
ACCEPTANCE_VERSION = "0.1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@lru_cache(maxsize=1)
def _registry() -> Any:
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    schemas = dict(P._schema_bundle())
    for schema in (C.candidate_schema_for("0.4"), C.artifact_schema_for("0.4")):
        schemas[schema["$id"]] = schema
    return Registry().with_resources(
        (uri, Resource.from_contents(schema, default_specification=DRAFT202012))
        for uri, schema in schemas.items()
    )


def _schema_errors(schema: dict[str, Any], value: Any) -> list[str]:
    return R._iter_schema_errors(schema, value, registry=_registry())


def build_source_scope(request: dict[str, Any]) -> dict[str, Any]:
    """Bind body/annotation fragments to original chapter code-point ranges.

    Only paired ``〈…〉`` marks establish annotations. A depth counter retains
    nested notes and notes crossing paragraph boundaries. ``〔…〕`` stays body
    text. No guessed continuation, normalized rewrite, or dropped source is
    permitted. A malformed delimiter or incomplete block map fails closed.
    """
    C._require_request(request)
    text = request["normalized_text"]
    content_sha = C.sha256_text(text)
    if request.get("normalized_sha256") != content_sha:
        raise PersistenceError("source_scope: normalized_sha256 does not match chapter text")
    chapter_start = request.get("chapter_start", 0)
    if type(chapter_start) is not int or chapter_start < 0:
        raise PersistenceError("source_scope: invalid chapter_start origin")
    chapter_end = request.get("chapter_end", chapter_start + len(text))
    if (
        type(chapter_start) is not int
        or type(chapter_end) is not int
        or chapter_start < 0
        or chapter_end - chapter_start != len(text)
    ):
        raise PersistenceError("source_scope: invalid chapter_start/chapter_end origin")
    for name in ("source_sha256", "normalized_sha256"):
        if not isinstance(request.get(name), str) or not _SHA256.fullmatch(request[name]):
            raise PersistenceError(f"source_scope: {name} must be a SHA-256")
    revision_sha = request.get("revision_normalized_sha256", content_sha)
    if not isinstance(revision_sha, str) or not _SHA256.fullmatch(revision_sha):
        raise PersistenceError("source_scope: revision_normalized_sha256 must be a SHA-256")

    cursor = 0
    for block in request["blocks"]:
        start, end = block.get("start"), block.get("end")
        if type(start) is not int or type(end) is not int or start != cursor:
            raise PersistenceError("source_scope: blocks must tile the whole chapter in order")
        if block.get("kind") not in ("body", "heading", "separator"):
            raise PersistenceError(f"source_scope: unsupported block kind {block.get('kind')!r}")
        expected_hash = C.sha256_text(text[start:end])
        if block.get("content_sha256", expected_hash) != expected_hash:
            raise PersistenceError(f"source_scope: block {block['block_id']!r} hash drift")
        cursor = end
    if cursor != len(text):
        raise PersistenceError("source_scope: blocks do not cover the whole chapter")

    ranges: list[tuple[int, int, str]] = []
    depth = 0
    start = 0
    for offset, char in enumerate(text):
        if char == "〈":
            if depth == 0:
                if start < offset:
                    ranges.append((start, offset, "body"))
                start = offset
            depth += 1
        elif char == "〉":
            if depth == 0:
                raise PersistenceError(f"source_scope: unmatched 〉 at chapter offset {offset}")
            depth -= 1
            if depth == 0:
                ranges.append((start, offset + 1, "annotation"))
                start = offset + 1
    if depth:
        raise PersistenceError(f"source_scope: unclosed 〈 at chapter offset {start}")
    if start < len(text):
        ranges.append((start, len(text), "body"))

    fragments: list[dict[str, Any]] = []
    body_ids: list[str] = []
    for block in request["blocks"]:
        for first, last, role in ranges:
            lo, hi = max(block["start"], first), min(block["end"], last)
            if lo >= hi:
                continue
            if role == "body" and (block["kind"] != "body" or not text[lo:hi].strip()):
                continue
            fragment = {
                "block_id": block["block_id"],
                "role": role,
                "start": lo,
                "end": hi,
                "text_sha256": C.sha256_text(text[lo:hi]),
            }
            fragment["id"] = "sf_" + sha256_json({
                "chapter_id": request["chapter_id"],
                "revision_id": request["revision_id"],
                "chapter_start": chapter_start,
                **fragment,
            })[:24]
            fragments.append(fragment)
            if role == "body" and block["block_id"] not in body_ids:
                body_ids.append(block["block_id"])
    if not body_ids:
        raise PersistenceError("source_scope: chapter has no translatable body outside annotations")
    return {
        "schema": SOURCE_SCOPE_SCHEMA,
        "version": SOURCE_SCOPE_VERSION,
        "chapter_id": request["chapter_id"],
        "revision_id": request["revision_id"],
        "source_sha256": request["source_sha256"],
        "normalized_sha256": request["normalized_sha256"],
        "revision_normalized_sha256": revision_sha,
        "chapter_content_sha256": content_sha,
        "chapter_start": chapter_start,
        "chapter_end": chapter_end,
        "offset_unit": C.OFFSET_UNIT,
        "body_block_ids": body_ids,
        "fragments": fragments,
    }


def _legacy_candidate(candidate: dict[str, Any], version: str) -> dict[str, Any]:
    """Use frozen validators on their own sub-document, never emit it."""
    subset = copy.deepcopy(candidate)
    subset.pop("source_scope", None)
    if version in ("0.1", "0.2"):
        subset.pop("person_states", None)
    if version == "0.1":
        subset.pop("reading", None)
    subset["version"] = version
    return subset


def _body_coverage_errors(
    request: dict[str, Any], candidate: dict[str, Any], scope: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    translation = candidate.get("translation")
    blocks = translation.get("blocks") if isinstance(translation, dict) else None
    if not isinstance(blocks, list):
        return errors  # Frozen validator reports malformed translation.
    for block in blocks:
        if not isinstance(block, dict):
            continue
        owner = f"translation {block.get('block_id')!r}"
        source_ids = block.get("source_block_ids")
        if not isinstance(source_ids, list):
            continue
        for block_id in source_ids:
            if not isinstance(block_id, str):
                continue
            if block_id not in scope["body_block_ids"]:
                errors.append(f"{owner} source block {block_id!r} is not body scope")
    return errors


def validate_staged_candidate(request: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Validate all 0.4 fields and the unchanged frozen 0.3 sub-document."""
    errors = _schema_errors(C.candidate_schema_for("0.4"), candidate)
    inherited: dict[str, Any] = {}
    expected_scope = None
    if not isinstance(request, dict):
        errors.append("request must be a JSON object")
    else:
        versions = request.get("schema_versions")
        if not isinstance(versions, dict) or versions.get("candidate") != "0.4":
            errors.append("request must explicitly select chapter candidate 0.4")
        for key in ("chapter_start", "chapter_end", "revision_normalized_sha256"):
            if key not in request:
                errors.append(f"request is missing {key}")
        try:
            expected_scope = build_source_scope(request)
        except (PersistenceError, TypeError, KeyError, ValueError) as exc:
            errors.append(f"source_scope: {exc}")
        if expected_scope is not None:
            if request.get("source_scope") != expected_scope:
                errors.append("request source_scope differs from the program-derived source scope")
            if request.get("required_block_ids") != expected_scope["body_block_ids"]:
                errors.append("request required_block_ids must equal the body scope block IDs")
    if isinstance(candidate, dict) and isinstance(request, dict):
        if expected_scope is not None and candidate.get("source_scope") != expected_scope:
            errors.append("candidate source_scope differs from the program-derived source scope")
        subset = _legacy_candidate(candidate, "0.3")
        # The base validator checks the exact full source and all of its
        # references. Only its required body list is generation-specific.
        inherited_request = copy.deepcopy(request)
        if expected_scope is not None:
            inherited_request["required_block_ids"] = list(expected_scope["body_block_ids"])
        try:
            inherited = P.validate_person_state_candidate(inherited_request, subset)
            if expected_scope is not None:
                errors.extend(_body_coverage_errors(request, candidate, expected_scope))
        except (PersistenceError, TypeError, AttributeError, KeyError, ValueError) as exc:
            errors.append(f"base contract validation failed: {type(exc).__name__}: {exc}")
    inherited_errors = P.flatten_person_state_errors(inherited) if inherited else []
    count = len(errors) + len(inherited_errors)
    return {
        "schema": "chronicle.staged-chapter-validation",
        "version": "0.1",
        "valid": count == 0,
        "passed": count == 0,
        "count": count,
        "errors": errors,
        "person_states": inherited,
    }


def flatten_staged_errors(report: dict[str, Any]) -> list[str]:
    return list(report.get("errors") or []) + [
        "base: " + error
        for error in P.flatten_person_state_errors(report.get("person_states") or {})
    ]


def validate_production_receipt(
    receipt: Any, *, request_fingerprint: str, candidate_sha256: str
) -> list[str]:
    """Validate receipt binding; persisted history authority is checked by the store."""
    schema = C.artifact_schema_for("0.4")
    errors = _schema_errors({
        "$ref": schema["$id"] + "#/$defs/production_receipt"
    }, receipt)
    if isinstance(receipt, dict):
        if receipt.get("request_fingerprint") != request_fingerprint:
            errors.append("production receipt request_fingerprint drift")
        if receipt.get("candidate_sha256") != candidate_sha256:
            errors.append("production receipt candidate_sha256 drift")
    return errors


def accept_staged_candidate(
    request: dict[str, Any],
    candidate: dict[str, Any],
    *,
    producing_run: dict[str, Any],
    production_receipt: dict[str, Any],
) -> dict[str, Any]:
    """Build actual 0.4 hashes/anchors/units only after full validation."""
    fresh = validate_staged_candidate(request, candidate)
    if not fresh["passed"]:
        raise PersistenceError("staged candidate failed validation: " + "; ".join(flatten_staged_errors(fresh)))
    if not isinstance(producing_run, dict):
        raise PersistenceError("producing_run must be a JSON object")
    for key in ("run_id", "model", "prompt_schema_version"):
        if not isinstance(producing_run.get(key), str) or not producing_run[key]:
            raise PersistenceError(f"producing_run requires non-empty {key!r}")
    fingerprint = C.request_fingerprint(request)
    candidate_sha = sha256_json(candidate)
    receipt_errors = validate_production_receipt(
        production_receipt, request_fingerprint=fingerprint, candidate_sha256=candidate_sha
    )
    if receipt_errors:
        raise PersistenceError("invalid production receipt: " + "; ".join(receipt_errors))
    anchors = P._merge_anchor_records(
        C.collect_anchors(request, _legacy_candidate(candidate, "0.1")),
        P.collect_person_state_anchors(candidate, request),
        "staged chapter acceptance",
    )
    core = {
        "schema": ARTIFACT_SCHEMA,
        "version": ARTIFACT_VERSION,
        "chapter_id": request["chapter_id"],
        "revision_id": request["revision_id"],
        "source_sha256": request["source_sha256"],
        "normalized_sha256": request["normalized_sha256"],
        "candidate": copy.deepcopy(candidate),
        "candidate_sha256": candidate_sha,
        "anchors": anchors,
        "request_fingerprint": fingerprint,
        "producing_run": copy.deepcopy(producing_run),
        "reading": copy.deepcopy(candidate["reading"]),
        "reading_sha256": sha256_json(candidate["reading"]),
        "person_states": copy.deepcopy(candidate["person_states"]),
        "person_states_sha256": sha256_json(candidate["person_states"]),
        "person_state_candidates": P.build_person_state_candidates(candidate, request),
        "production_receipt": copy.deepcopy(production_receipt),
    }
    artifact_sha = sha256_json(core)
    artifact = {
        **core,
        "artifact_sha256": artifact_sha,
        "reading_units": R._resolve_reading_units(candidate, request, artifact_sha),
    }
    schema_errors = _schema_errors(C.artifact_schema_for("0.4"), artifact)
    if schema_errors:
        raise PersistenceError("invalid accepted staged artifact: " + "; ".join(schema_errors))
    return artifact
