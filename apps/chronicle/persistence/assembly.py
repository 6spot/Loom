"""Current deterministic chapter assembly for the Chronicle staged worker.

The durable worker accepts only T01's current chapter artifacts and the T03
natural-chapter plan. This module remaps chapter-local references into one
revision-scoped bundle, preserves source evidence, and emits a content-bound
report for the resolve/review/publish stages. It has no model or database
access; retired C1 chunk assembly is no longer a production code path.
"""

from __future__ import annotations

import copy
import re
from typing import Any

import person_state_assembly as _person_state_assembly
from c0_schema import canonical_schema
from common import PersistenceError, canonical_json_bytes, sha256_json

#: Version of the chapter-assembly pipeline step (C2-R1-T07).
CHAPTER_ASSEMBLY_VERSION = "c2r1-assembly-v1"

#: Chapter plan version consumed by chapter assembly (T03 output).
CHAPTER_PLAN_VERSION = "c2r1-chapters-v1"

#: Schema marker for the chapter-assembly report emitted beside the bundle.
CHAPTER_REPORT_SCHEMA = "chronicle.chapter-assembly-report"
CHAPTER_REPORT_VERSION = "0.1"

#: Accepted chapter artifact marker (the sole accepted input).
CHAPTER_ARTIFACT_SCHEMA = "chronicle.chapter-artifact"
CHAPTER_ARTIFACT_VERSION = "0.4"

#: Internal aliases retained for callers that inspect the assembly report;
#: every alias names the same current generation, never a legacy protocol.
CHAPTER_READING_ARTIFACT_VERSION = CHAPTER_ARTIFACT_VERSION

#: Model-generatable chapter candidate marker (embedded in artifacts).
CHAPTER_CANDIDATE_SCHEMA = "chronicle.chapter-candidate"
CHAPTER_CANDIDATE_VERSION = "0.4"

#: Internal alias for the current candidate generation.
CHAPTER_READING_CANDIDATE_VERSION = CHAPTER_CANDIDATE_VERSION

#: Internal alias for the current artifact generation.
CHAPTER_PERSON_STATE_ARTIFACT_VERSION = CHAPTER_ARTIFACT_VERSION

#: Internal alias for the current candidate generation.
CHAPTER_PERSON_STATE_CANDIDATE_VERSION = CHAPTER_CANDIDATE_VERSION

# Staged production is the current chapter product and retains the bound
# reading/person-state fields and production receipt.
CHAPTER_STAGED_ARTIFACT_VERSION = CHAPTER_ARTIFACT_VERSION
CHAPTER_STAGED_CANDIDATE_VERSION = CHAPTER_CANDIDATE_VERSION

_T_BLOCK_ID_RE = re.compile(r"^t_(\d+)$")
_MENTION_ID_RE = re.compile(r"^m_(\d+)$")

#: Chapter-candidate Claim reference kinds normalized to the C0 bundle
#: vocabulary at the assembly output boundary. The T01 candidate contract
#: uses ``entity``/``event`` while ``chronicle-v0.1`` requires
#: ``entity_ref``/``event_ref``. ``literal``/null objects are preserved.
_CLAIM_KIND_TO_C0 = {
    "entity": "entity_ref",
    "entity_ref": "entity_ref",
    "event": "event_ref",
    "event_ref": "event_ref",
}

#: Reused C0 contract-first extraction contract (contract_v0 / repair_v0).
CONTRACT_VERSION = "0.2"

#: Reused C0 staged-bundle schema version.
SCHEMA_VERSION = "0.1"

#: Control-plane artifact type for the persisted assembly output.
ARTIFACT_TYPE = "assembled-source-bundle"

#: Marker proving the assembled bundle is source-owned processing output.
NON_AUTHORITATIVE_NOTE = (
    "assembled source bundle is deterministic processing output over one "
    "immutable document revision, not historical authority; canonical "
    "identity remains owned by the C0 staged/resolution/canonical path"
)

_TEMP_ID_RE = re.compile(r"^(src|ent|evt|clm)_(\d+)$")


def validate_assembled_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Validate the current staged bundle against the canonical C0 schema.

    Returns a deterministic report (fail closed: schema violations raise
    :class:`PersistenceError` instead of returning a soft report).
    """
    if not isinstance(bundle, dict):
        raise PersistenceError("assembled bundle must be a JSON object")
    schema = canonical_schema()
    from jsonschema import Draft202012Validator, FormatChecker

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    found = sorted(validator.iter_errors(bundle), key=lambda e: list(e.absolute_path))
    errors = []
    for error in found:
        where = "/".join(str(part) for part in error.absolute_path) or "$"
        errors.append(f"{where}: {error.message}")
    if errors:
        raise PersistenceError(
            "assembled bundle failed the canonical C0 schema: " + "; ".join(errors)
        )
    return {
        "schema": "chronicle.source-assembly-validation",
        "version": "0.1",
        "assembly_version": CHAPTER_ASSEMBLY_VERSION,
        "contract_version": CONTRACT_VERSION,
        "passed": True,
        "count": 0,
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Chapter assembly (C2-R1-T07)
# ---------------------------------------------------------------------------


def _remapped_chapter_id(prefix: str, chapter_index: int, local: str) -> str:
    """Deterministic revision-scoped temp ID for one chapter record.

    Reuses the original namespace rule: ``(chapter_index, local_ref)`` maps
    into ``{prefix}_{chapter_index:03d}{number:03d}`` so ``ent_001`` in
    chapter 0 (``ent_000001``) can never collide with ``ent_001`` in
    chapter 1 (``ent_001001``). Satisfies the C0 temp-ID pattern.
    """
    match = _TEMP_ID_RE.match(local)
    if match and match.group(1) == prefix:
        number = int(match.group(2))
    else:
        number = 0
    if chapter_index > 999 or number > 999:
        raise PersistenceError(
            f"chapter {chapter_index} record {local!r} exceeds the revision-scoped ID space"
        )
    return f"{prefix}_{chapter_index:03d}{number:03d}"


def _remapped_translation_block_id(chapter_index: int, local: str, position: int) -> str:
    match = _T_BLOCK_ID_RE.match(local) if isinstance(local, str) else None
    number = int(match.group(1)) if match else (position + 1)
    if chapter_index > 999 or number > 999:
        raise PersistenceError(
            f"chapter {chapter_index} translation block {local!r} exceeds the ID space"
        )
    return f"t_{chapter_index:03d}{number:03d}"


def _remapped_mention_id(chapter_index: int, local: str, position: int) -> str:
    match = _MENTION_ID_RE.match(local) if isinstance(local, str) else None
    number = int(match.group(1)) if match else (position + 1)
    if chapter_index > 999 or number > 999:
        raise PersistenceError(
            f"chapter {chapter_index} mention {local!r} exceeds the ID space"
        )
    return f"m_{chapter_index:03d}{number:03d}"


def _chapter_inputs(value: Any, description: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise PersistenceError(f"{description} must be a non-empty array")
    for item in value:
        if not isinstance(item, dict):
            raise PersistenceError(f"{description} must hold JSON objects")
    return list(value)


def _validate_chapter_plan(chapter_plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate the T03 plan shape; return chapters sorted by chapter_index."""
    if not isinstance(chapter_plan, dict):
        raise PersistenceError("chapter_plan must be a JSON object")
    if chapter_plan.get("version", CHAPTER_PLAN_VERSION) != CHAPTER_PLAN_VERSION:
        raise PersistenceError(
            f"chapter plan version must be {CHAPTER_PLAN_VERSION!r}, "
            f"got {chapter_plan.get('version')!r}"
        )
    for key in ("revision_id", "source_sha256", "normalized_sha256"):
        if not isinstance(chapter_plan.get(key), str) or not chapter_plan.get(key):
            raise PersistenceError(f"chapter_plan is missing {key!r}")
    chapters = chapter_plan.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise PersistenceError("chapter_plan chapters must be a non-empty array")
    for chapter in chapters:
        if not isinstance(chapter, dict):
            raise PersistenceError("chapter_plan chapters must hold JSON objects")
        if not isinstance(chapter.get("chapter_id"), str) or not chapter.get("chapter_id"):
            raise PersistenceError("chapter_plan chapter requires a chapter_id")
        if not isinstance(chapter.get("content_sha256"), str) or not chapter.get(
            "content_sha256"
        ):
            raise PersistenceError(
                f"chapter_plan chapter {chapter.get('chapter_id')!r} requires "
                "its content_sha256 chapter hash; a plan without "
                "per-chapter content binding cannot enter assembly"
            )
        index = chapter.get("chapter_index")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise PersistenceError(
                f"chapter {chapter.get('chapter_id')!r} chapter_index must be a non-negative integer"
            )
    ordered = sorted(chapters, key=lambda c: c["chapter_index"])
    indexes = [c["chapter_index"] for c in ordered]
    if len(set(indexes)) != len(indexes):
        raise PersistenceError(f"chapter_plan chapter indexes are not unique: {indexes}")
    if indexes != list(range(len(ordered))):
        raise PersistenceError(
            f"chapter_plan chapter indexes must be contiguous 0..{len(ordered) - 1}, got {indexes}"
        )
    ids = [c["chapter_id"] for c in ordered]
    if len(set(ids)) != len(ids):
        raise PersistenceError(f"chapter_plan chapter ids are not unique: {ids}")
    return ordered


def _validate_accepted_chapter_artifact(
    artifact: dict[str, Any], *, position: int
) -> dict[str, Any]:
    """Structural fail-closed check for one T01 accepted artifact."""
    owner = f"accepted_artifacts[{position}]"
    if not isinstance(artifact, dict):
        raise PersistenceError(f"{owner} must be a JSON object")
    version = artifact.get("version")
    if artifact.get("schema") != CHAPTER_ARTIFACT_SCHEMA or version != CHAPTER_ARTIFACT_VERSION:
        raise PersistenceError(
            f"{owner} must be the current {CHAPTER_ARTIFACT_SCHEMA}/"
            f"{CHAPTER_ARTIFACT_VERSION}; retired chapter generations are rejected"
        )
    candidate_version = CHAPTER_CANDIDATE_VERSION
    import staged_chapter_contract as staged

    errors = staged._schema_errors(staged.C.artifact_schema_for(CHAPTER_ARTIFACT_VERSION), artifact)
    errors.extend(staged.validate_production_receipt(
        artifact.get("production_receipt"),
        request_fingerprint=artifact.get("request_fingerprint"),
        candidate_sha256=artifact.get("candidate_sha256"),
    ))
    if errors:
        raise PersistenceError(f"{owner} invalid current artifact: " + "; ".join(errors))
    for key in ("chapter_id", "revision_id", "source_sha256", "normalized_sha256",
                "candidate_sha256", "request_fingerprint"):
        if not isinstance(artifact.get(key), str) or not artifact.get(key):
            raise PersistenceError(f"{owner} is missing {key!r}")
    candidate = artifact.get("candidate")
    if not isinstance(candidate, dict):
        raise PersistenceError(f"{owner} is missing its accepted candidate")
    if candidate.get("schema") != CHAPTER_CANDIDATE_SCHEMA or candidate.get("version") != candidate_version:
        raise PersistenceError(
            f"{owner} candidate must be {CHAPTER_CANDIDATE_SCHEMA}/{candidate_version}"
        )
    if sha256_json(candidate) != artifact["candidate_sha256"]:
        raise PersistenceError(
            f"{owner} candidate bytes do not match candidate_sha256; "
            "tampered or unaccepted products are rejected"
        )
    if candidate.get("chapter_id") != artifact["chapter_id"]:
        raise PersistenceError(
            f"{owner} candidate chapter {candidate.get('chapter_id')!r} does not match "
            f"artifact chapter {artifact['chapter_id']!r}"
        )
    bundle = candidate.get("bundle")
    if not isinstance(bundle, dict):
        raise PersistenceError(f"{owner} candidate is missing its bundle")
    if bundle.get("schema_version") != SCHEMA_VERSION:
        raise PersistenceError(
            f"{owner} bundle schema_version must be {SCHEMA_VERSION!r}"
        )
    source = bundle.get("source")
    if not isinstance(source, dict):
        raise PersistenceError(f"{owner} bundle is missing its source")
    entities = bundle.get("entities")
    events = bundle.get("events")
    claims = bundle.get("claims")
    for name, collection in (("entities", entities), ("events", events), ("claims", claims)):
        if not isinstance(collection, list):
            raise PersistenceError(f"{owner} bundle {name} must be an array")
        for record in collection:
            if not isinstance(record, dict):
                raise PersistenceError(f"{owner} bundle {name} must hold JSON objects")
    translation = candidate.get("translation")
    if not isinstance(translation, dict) or not isinstance(translation.get("blocks"), list):
        raise PersistenceError(f"{owner} candidate is missing translation.blocks")
    for name in ("mentions", "record_sources", "anchors"):
        collection = candidate.get(name) if name != "anchors" else artifact.get(name)
        if not isinstance(collection, list):
            raise PersistenceError(f"{owner} is missing {name!r} array")
            # anchors live on the artifact; mentions/record_sources on the candidate.
    # Canonical-identity discipline: nothing accepted may carry canonical IDs.
    # (T01 already enforces this; re-check fail-closed so a forged artifact
    # can never leak direct canonical assignment into the staged bundle.)
    bundle_records: list[tuple[str, dict[str, Any]]] = []
    for collection_name, collection in (("entities", entities), ("events", events), ("claims", claims)):
        for record in collection:
            bundle_records.append((collection_name, record))
    seen: set[str] = set()
    source_temp = source.get("temp_id")
    if not isinstance(source_temp, str) or not source_temp.startswith("src_"):
        raise PersistenceError(f"{owner} source temp_id must carry the 'src_' prefix")
    seen.add(source_temp)
    for collection_name, record in bundle_records:
        prefix = {"entities": "ent_", "events": "evt_", "claims": "clm_"}[collection_name]
        temp_id = record.get("temp_id")
        if not isinstance(temp_id, str) or not temp_id:
            raise PersistenceError(f"{owner} {collection_name} record requires a string temp_id")
        if not temp_id.startswith(prefix):
            raise PersistenceError(
                f"{owner} {temp_id!r} temp_id must carry the {prefix!r} {collection_name} prefix"
            )
        if temp_id in seen:
            raise PersistenceError(f"{owner} carries duplicate temp_id {temp_id!r}")
        seen.add(temp_id)
        if "id" in record:
            raise PersistenceError(
                f"{owner} {collection_name} record {temp_id!r} must not carry canonical identity"
            )
        resolution = record.get("resolution")
        if isinstance(resolution, dict):
            if resolution.get("canonical_id") is not None:
                raise PersistenceError(
                    f"{owner} {collection_name} record {temp_id!r} carries a nested canonical ID"
                )
            candidates = resolution.get("candidate_ids")
            if candidates is not None and candidates != []:
                raise PersistenceError(
                    f"{owner} {collection_name} record {temp_id!r} carries nested candidate IDs"
                )
            if collection_name == "entities" and resolution.get("status") != "unresolved":
                raise PersistenceError(
                    f"{owner} entity record {temp_id!r} has resolution status "
                    f"{resolution.get('status')!r}; assembly input must be unresolved/temp-ID-only"
                )
    # ``artifact_sha256`` is the accepted product's own canonical hash. The
    # current staged contract binds it to the artifact core excluding
    # ``reading_units``; the accepted reading unit IDs are derived from that
    # value, so recomputing a whole-artifact hash here would disagree with the
    # artifact the model accepted.
    artifact_sha256 = sha256_json(artifact)
    reading: dict[str, Any] | None = None
    reading_units: list[dict[str, Any]] = []
    person_states: dict[str, Any] | None = None
    person_state_candidates: list[dict[str, Any]] = []
    if version == CHAPTER_ARTIFACT_VERSION:
        accepted_sha = artifact.get("artifact_sha256")
        if not isinstance(accepted_sha, str) or not accepted_sha:
            raise PersistenceError(
                f"{owner} {version} artifact is missing artifact_sha256"
            )
        # The accepted artifact hash binds the artifact *core*. ``reading_units``
        # is excluded because its unit IDs are derived from ``artifact_sha256``;
        # the program-computed ``person_state_candidates`` keys do not depend on
        # that hash, so they stay inside the core and are hash-bound (C2-R3-T03
        # review: a truncated/edited candidate list must not survive).
        excluded = {"artifact_sha256", "reading_units"}
        core = {key: value for key, value in artifact.items() if key not in excluded}
        if sha256_json(core) != accepted_sha:
            raise PersistenceError(
                f"{owner} artifact core does not match artifact_sha256; "
                "tampered or unaccepted products are rejected"
            )
        artifact_sha256 = accepted_sha
        reading = candidate.get("reading")
        if not isinstance(reading, dict) or not isinstance(reading.get("units"), list):
            raise PersistenceError(f"{owner} {version} candidate is missing its reading.units")
        reading_sha = artifact.get("reading_sha256")
        if not isinstance(reading_sha, str) or not reading_sha:
            raise PersistenceError(f"{owner} {version} artifact is missing reading_sha256")
        if sha256_json(reading) != reading_sha:
            raise PersistenceError(
                f"{owner} reading bytes do not match reading_sha256; "
                "tampered or unaccepted products are rejected"
            )
        resolved = artifact.get("reading_units")
        if not isinstance(resolved, list):
            raise PersistenceError(f"{owner} {version} artifact is missing reading_units")
        if len(resolved) != len(reading["units"]):
            raise PersistenceError(
                f"{owner} reading_units count {len(resolved)} does not match "
                f"candidate reading units {len(reading['units'])}"
            )
        for unit_index, unit in enumerate(resolved):
            if not isinstance(unit, dict) or not isinstance(unit.get("block_id"), str) or not unit["block_id"]:
                raise PersistenceError(
                    f"{owner} reading_units[{unit_index}] must name a translation block_id"
                )
        reading_units = list(resolved)
    if version == CHAPTER_ARTIFACT_VERSION:
        person_states = artifact.get("person_states")
        if not isinstance(person_states, dict):
            raise PersistenceError(f"{owner} current artifact is missing its person_states block")
        for name in (
            "phases",
            "phase_orders",
            "unit_phases",
            "facts",
            "continuities",
            "disagreements",
        ):
            if not isinstance(person_states.get(name), list):
                raise PersistenceError(
                    f"{owner} person_states.{name} must be an array"
                )
        if candidate.get("person_states") != person_states:
            raise PersistenceError(
                f"{owner} accepted candidate person_states do not match the "
                "artifact person_states block; tampered or unaccepted products "
                "are rejected"
            )
        person_states_sha = artifact.get("person_states_sha256")
        if not isinstance(person_states_sha, str) or not person_states_sha:
            raise PersistenceError(f"{owner} current artifact is missing person_states_sha256")
        if sha256_json(person_states) != person_states_sha:
            raise PersistenceError(
                f"{owner} person_states bytes do not match person_states_sha256; "
                "tampered or unaccepted products are rejected"
            )
        candidates = artifact.get("person_state_candidates")
        if not isinstance(candidates, list):
            raise PersistenceError(
                f"{owner} current artifact is missing its person_state_candidates keys"
            )
        for entry in candidates:
            if not isinstance(entry, dict) or not isinstance(entry.get("item_ref"), str):
                raise PersistenceError(
                    f"{owner} person_state_candidates entries must name an item_ref"
                )
        person_state_candidates = list(candidates)
    return {
        "chapter_id": artifact["chapter_id"],
        "revision_id": artifact["revision_id"],
        "source_sha256": artifact["source_sha256"],
        "normalized_sha256": artifact["normalized_sha256"],
        "artifact_version": version,
        "candidate": candidate,
        "bundle": bundle,
        "source": source,
        "entities": list(entities),
        "events": list(events),
        "claims": list(claims),
        "translation": translation,
        "mentions": list(candidate["mentions"]),
        "record_sources": list(candidate["record_sources"]),
        "anchors": list(artifact["anchors"]),
        "candidate_sha256": artifact["candidate_sha256"],
        "request_fingerprint": artifact["request_fingerprint"],
        "artifact_sha256": artifact_sha256,
        "reading": reading,
        "reading_units": reading_units,
        "person_states": person_states,
        "person_state_candidates": person_state_candidates,
    }


def assemble_chapters(
    *,
    accepted_artifacts: list[dict[str, Any]],
    chapter_plan: dict[str, Any],
) -> dict[str, Any]:
    """Assemble accepted chapter artifacts into one revision-staged bundle.

    Inputs are current accepted artifacts (``chronicle.chapter-artifact /
    0.4``) plus the T03 chapter plan; one assembly call never mixes
    retired generations. Every
    expected chapter must have
    exactly one accepted artifact: missing chapters, extra chapters,
    duplicate chapters, mixed revisions, or unaccepted/tampered products
    fail closed instead of producing a partial book bundle.

    Each ``(chapter_index, local temp_id)`` maps into one revision-scoped
    ref reusing the original namespace rule, and every reference — C0
    claim/event fields, translation entity/event refs, mentions, and
    record_sources — is rewritten through that same mapping. Translation
    blocks without a Claim are preserved. One revision keeps exactly one
    ``src_001`` source; per-record ``chapter_by_ref`` plus exact artifact
    provenance serves T08 candidacy and T10 evidence lookup.

    Unlike the chunk path, no boundary-duplicate suppression and no
    automatic same-link run here: different chapters may describe the
    same occurrence, but this stage keeps them as distinct pending
    records and never merges by name.

    Returns ``{"bundle", "translation_blocks", "mentions",
    "record_sources", "anchors", "reading_units", "person_states",
    "person_state_evidence", "report"}``. The accepted reading and
    person-state evidence is lifted into the same revision namespace from
    :mod:`person_state_assembly`.
    Deterministic: unchanged inputs yield byte-identical canonical JSON.
    No model calls, no worker changes, no source-candidate mutation.
    """
    plan_chapters = _validate_chapter_plan(chapter_plan)
    if not isinstance(accepted_artifacts, list) or not accepted_artifacts:
        raise PersistenceError("assemble_chapters requires at least one accepted artifact")
    normalized = [
        _validate_accepted_chapter_artifact(artifact, position=position)
        for position, artifact in enumerate(accepted_artifacts)
    ]

    plan_revision = (
        chapter_plan["revision_id"],
        chapter_plan["source_sha256"],
    )
    plan_content_by_id = {
        c["chapter_id"]: c.get("content_sha256") for c in plan_chapters
    }
    plan_chapter_by_id = {c["chapter_id"]: c for c in plan_chapters}
    for item in normalized:
        pair = (item["revision_id"], item["source_sha256"])
        if pair != plan_revision:
            raise PersistenceError(
                f"artifact chapter {item['chapter_id']!r} revision pair {pair!r} does not match "
                f"chapter plan pair {plan_revision!r}; refusing to mix revisions in one source bundle"
            )
        # Chapter-granularity binding: the artifact's normalized hash is
        # the chapter slice hash (T01 identity check), so it must equal
        # the plan chapter's required content hash — never the
        # full-revision hash, and never unchecked.
        planned = plan_chapter_by_id.get(item["chapter_id"])
        if planned is None:
            raise PersistenceError(
                f"artifact chapter {item['chapter_id']!r} is not present in "
                "the frozen chapter plan"
            )
        expected_content = plan_content_by_id[item["chapter_id"]]
        if item["normalized_sha256"] != expected_content:
            raise PersistenceError(
                f"artifact chapter {item['chapter_id']!r} normalized hash "
                f"{item['normalized_sha256']!r} does not match the planned "
                "chapter content hash; refusing bytes outside the plan"
            )
        scope = item["candidate"].get("source_scope")
        if not isinstance(scope, dict):
            raise PersistenceError(
                f"current artifact chapter {item['chapter_id']!r} is missing source_scope"
            )
        if (
            any(scope.get(key) != item[key] for key in (
                "chapter_id", "revision_id", "source_sha256", "normalized_sha256",
            ))
            or scope.get("chapter_content_sha256") != item["normalized_sha256"]
            or scope.get("chapter_start") != planned["start"]
            or scope.get("chapter_end") != planned["end"]
            or scope.get("revision_normalized_sha256") != chapter_plan["normalized_sha256"]
        ):
            raise PersistenceError(
                "current source scope origin differs from the frozen chapter plan"
            )
    if len({(item["revision_id"], item["source_sha256"]) for item in normalized}) != 1:
        raise PersistenceError("assembly artifacts span multiple revisions/source hashes (fail closed)")
    artifact_versions = {item["artifact_version"] for item in normalized}
    if len(artifact_versions) != 1:
        raise PersistenceError(
            f"assembly artifacts mix generation versions {sorted(artifact_versions)}; "
            "refusing to mix chapter product generations"
        )
    if artifact_versions != {CHAPTER_ARTIFACT_VERSION}:
        raise PersistenceError(
            "assembly accepts only the current 0.4 artifact generation"
        )
    reading_path = True
    person_state_path = True

    expected_ids = [c["chapter_id"] for c in plan_chapters]
    seen_ids: set[str] = set()
    for item in normalized:
        if item["chapter_id"] in seen_ids:
            raise PersistenceError(
                f"duplicate accepted artifact for chapter {item['chapter_id']!r}"
            )
        seen_ids.add(item["chapter_id"])
    missing = [cid for cid in expected_ids if cid not in seen_ids]
    if missing:
        raise PersistenceError(
            f"missing accepted artifacts for chapters {missing}; "
            "refusing to present a finished subset as the whole book"
        )
    extra = sorted(seen_ids - set(expected_ids))
    if extra:
        raise PersistenceError(
            f"unexpected accepted artifacts for chapters {extra}; "
            "refusing to assemble chapters outside the plan"
        )

    plan_by_id = {c["chapter_id"]: c for c in plan_chapters}
    ordered = sorted(normalized, key=lambda item: plan_by_id[item["chapter_id"]]["chapter_index"])

    revision_id, source_sha256 = plan_revision
    normalized_sha256 = chapter_plan["normalized_sha256"]
    id_map: dict[tuple[int, str], str] = {}
    revision_ref_owner: dict[str, tuple[int, str]] = {}
    chapter_by_ref: dict[str, str] = {}
    local_to_revision: dict[str, str] = {}
    provenance: dict[str, dict[str, Any]] = {}
    chapter_artifacts: dict[str, str] = {}

    def _register(chapter_index: int, prefix: str, records: list[dict[str, Any]]) -> None:
        for position, record in enumerate(records):
            old = record.get("temp_id")
            if not isinstance(old, str) or not old:
                raise PersistenceError(
                    f"chapter {chapter_index} {prefix} record requires a temp_id"
                )
            match = _TEMP_ID_RE.match(old)
            local = old if (match and match.group(1) == prefix) else f"{prefix}_{position + 1:03d}"
            new = _remapped_chapter_id(prefix, chapter_index, local)
            key = (chapter_index, old)
            if key in id_map and id_map[key] != new:
                raise PersistenceError(f"remapped ID conflict at {key!r} (fail closed)")
            owner = revision_ref_owner.get(new)
            if owner is not None and owner != key:
                raise PersistenceError(
                    f"remapped ID collision at {new!r} between {owner!r} and {key!r} (fail closed)"
                )
            revision_ref_owner[new] = key
            id_map[key] = new

    for item in ordered:
        chapter_index = plan_by_id[item["chapter_id"]]["chapter_index"]
        _register(chapter_index, "ent", item["entities"])
        _register(chapter_index, "evt", item["events"])
        _register(chapter_index, "clm", item["claims"])

    for (chapter_index, local), new in id_map.items():
        chapter_id = next(
            item["chapter_id"] for item in ordered
            if plan_by_id[item["chapter_id"]]["chapter_index"] == chapter_index
        )
        chapter_by_ref[new] = chapter_id
        local_to_revision[f"({chapter_index},{local})"] = new

    # -- single revision source ------------------------------------------------
    titles: list[str] = []
    for item in ordered:
        title = item["source"].get("title")
        if isinstance(title, str) and title and title not in titles:
            titles.append(title)
    if not titles:
        raise PersistenceError("assembled source requires a title")
    merged_source = copy.deepcopy(ordered[0]["source"])
    merged_source["temp_id"] = "src_001"
    merged_source["title"] = titles[0]

    entity_ids: set[str] = set()
    event_ids: set[str] = set()
    final_entities: list[dict[str, Any]] = []
    final_events: list[dict[str, Any]] = []
    final_claims: list[dict[str, Any]] = []

    for item in ordered:
        chapter_id = item["chapter_id"]
        chapter_index = plan_by_id[chapter_id]["chapter_index"]

        def _map(local: Any) -> Any:
            if isinstance(local, str) and (chapter_index, local) in id_map:
                return id_map[(chapter_index, local)]
            return local

        for entity in item["entities"]:
            record = copy.deepcopy(entity)
            record["temp_id"] = id_map[(chapter_index, entity["temp_id"])]
            entity_ids.add(record["temp_id"])
            final_entities.append(record)
        for event in item["events"]:
            record = copy.deepcopy(event)
            record["temp_id"] = id_map[(chapter_index, event["temp_id"])]
            participants = []
            for participant in record.get("participants") or []:
                if isinstance(participant, dict):
                    participant = dict(participant)
                    participant["entity_ref"] = _map(participant.get("entity_ref"))
                participants.append(participant)
            record["participants"] = participants
            record["places"] = [_map(ref) for ref in record.get("places") or []]
            if record.get("parent_event_ref") is not None:
                record["parent_event_ref"] = _map(record.get("parent_event_ref"))
            event_ids.add(record["temp_id"])
            final_events.append(record)
        for claim in item["claims"]:
            record = copy.deepcopy(claim)
            record["temp_id"] = id_map[(chapter_index, claim["temp_id"])]
            for field in ("subject", "object"):
                ref = record.get(field)
                # Output boundary: normalize the chapter-candidate
                # entity/event vocabulary to the C0 bundle vocabulary
                # (entity_ref/event_ref). literal/null objects carry no
                # revision ref and are preserved verbatim.
                if ref is None:
                    continue
                if not isinstance(ref, dict):
                    continue
                kind = ref.get("kind")
                if kind in _CLAIM_KIND_TO_C0:
                    ref = dict(ref)
                    ref["kind"] = _CLAIM_KIND_TO_C0[kind]
                    ref["ref"] = _map(ref.get("ref"))
                    record[field] = ref
            evidence = dict(record.get("evidence") or {})
            evidence["source_ref"] = "src_001"
            record["evidence"] = evidence
            final_claims.append(record)

    claim_ids: set[str] = {record["temp_id"] for record in final_claims}

    # -- translation / mentions / record_sources through the same mapping -----
    translation_blocks: list[dict[str, Any]] = []
    out_mentions: list[dict[str, Any]] = []
    out_record_sources: list[dict[str, Any]] = []
    merged_anchors: list[dict[str, Any]] = []
    # ``(chapter_index, chapter-local block_id) -> revision block_id``: the
    # reading projection joins its units onto these remapped blocks. The
    # reverse owner map fails closed when two distinct local blocks would
    # collide, and blocks are emitted in source order (never re-sorted by the
    # generated ID).
    block_id_map: dict[tuple[int, str], str] = {}
    block_revision_owner: dict[str, str] = {}

    for item in ordered:
        chapter_id = item["chapter_id"]
        chapter_index = plan_by_id[chapter_id]["chapter_index"]

        def _map(local: Any) -> Any:
            if isinstance(local, str) and (chapter_index, local) in id_map:
                return id_map[(chapter_index, local)]
            return local

        for position, block in enumerate(item["translation"].get("blocks") or []):
            if not isinstance(block, dict):
                raise PersistenceError(
                    f"chapter {chapter_index} translation block must be a JSON object"
                )
            local_block = block.get("block_id")
            if not isinstance(local_block, str) or not local_block:
                raise PersistenceError(
                    f"chapter {chapter_index} translation block at {position} requires a block_id"
                )
            block_key = (chapter_index, local_block)
            if block_key in block_id_map:
                raise PersistenceError(
                    f"chapter {chapter_index} repeats translation block {local_block!r} (fail closed)"
                )
            out = copy.deepcopy(block)
            revision_block = _remapped_translation_block_id(chapter_index, local_block, position)
            owner = block_revision_owner.get(revision_block)
            if owner is not None and owner != local_block:
                raise PersistenceError(
                    f"chapter {chapter_index} local blocks {owner!r} and {local_block!r} "
                    f"both remap to {revision_block!r}; refusing an ambiguous block ID"
                )
            block_revision_owner[revision_block] = local_block
            block_id_map[block_key] = revision_block
            out["block_id"] = revision_block
            out["chapter_id"] = chapter_id
            out["chapter_index"] = chapter_index
            entity_refs = []
            for ref in block.get("entity_refs") or []:
                if not isinstance(ref, dict) or ref.get("kind") != "entity":
                    raise PersistenceError(
                        f"chapter {chapter_index} translation block has invalid entity ref"
                    )
                ref = dict(ref)
                ref["ref"] = _map(ref.get("ref"))
                entity_refs.append(ref)
            event_refs = []
            for ref in block.get("event_refs") or []:
                if not isinstance(ref, dict) or ref.get("kind") != "event":
                    raise PersistenceError(
                        f"chapter {chapter_index} translation block has invalid event ref"
                    )
                ref = dict(ref)
                ref["ref"] = _map(ref.get("ref"))
                event_refs.append(ref)
            out["entity_refs"] = entity_refs
            out["event_refs"] = event_refs
            # source_block_ids stay chapter-local (chapter-production §4):
            # they address the chapter request blocks, never revision refs.
            translation_blocks.append(out)

        for position, mention in enumerate(item["mentions"]):
            if not isinstance(mention, dict):
                raise PersistenceError(f"chapter {chapter_index} mention must be a JSON object")
            out = copy.deepcopy(mention)
            out["mention_id"] = _remapped_mention_id(chapter_index, mention.get("mention_id"), position)
            out["chapter_id"] = chapter_id
            out["chapter_index"] = chapter_index
            target = mention.get("target_ref")
            out["target_ref"] = _map(target) if target is not None else None
            out["candidate_refs"] = [_map(ref) for ref in mention.get("candidate_refs") or []]
            out_mentions.append(out)

        for entry in item["record_sources"]:
            if not isinstance(entry, dict):
                raise PersistenceError(f"chapter {chapter_index} record_sources entry must be an object")
            local_ref = entry.get("record_ref")
            mapped = _map(local_ref)
            if mapped == local_ref or not isinstance(mapped, str):
                raise PersistenceError(
                    f"chapter {chapter_index} record_sources entry references unknown record {local_ref!r}"
                )
            out = copy.deepcopy(entry)
            out["record_ref"] = mapped
            out["chapter_id"] = chapter_id
            out["chapter_index"] = chapter_index
            out_record_sources.append(out)

        for anchor in item["anchors"]:
            if not isinstance(anchor, dict):
                raise PersistenceError(f"chapter {chapter_index} anchor must be a JSON object")
            if anchor.get("chapter_id") != chapter_id:
                raise PersistenceError(
                    f"chapter {chapter_index} anchor {anchor.get('anchor_id')!r} belongs to "
                    f"{anchor.get('chapter_id')!r}; refusing cross-chapter anchors"
                )
            if anchor.get("revision_id") != revision_id:
                raise PersistenceError(
                    f"chapter {chapter_index} anchor revision mismatch (fail closed)"
                )
            merged_anchors.append(copy.deepcopy(anchor))

    # -- reading annotations through the same mapping (C2-R2-T04) -------------
    # The reading projection consumes these remapped units: chapter-local
    # refs are lifted into revision refs exactly like every other reference,
    # so cross-chapter names/local IDs can never be joined by name or leak a
    # chapter-local identity into the published reading index.
    assembled_reading_units: list[dict[str, Any]] = []
    if reading_path:
        for item in ordered:
            chapter_id = item["chapter_id"]
            chapter_index = plan_by_id[chapter_id]["chapter_index"]

            def _map_reading(local: Any, chapter_index: int = chapter_index) -> Any:
                if isinstance(local, str) and (chapter_index, local) in id_map:
                    return id_map[(chapter_index, local)]
                return local

            def _map_block(local: Any, chapter_index: int = chapter_index) -> Any:
                if isinstance(local, str) and (chapter_index, local) in block_id_map:
                    return block_id_map[(chapter_index, local)]
                return local

            for unit in item["reading_units"]:
                local_block = unit.get("block_id")
                revision_block = block_id_map.get((chapter_index, local_block))
                if revision_block is None:
                    raise PersistenceError(
                        f"chapter {chapter_index} reading unit references unknown block {local_block!r}"
                    )
                narrative = unit.get("narrative_time")
                narrative = narrative if isinstance(narrative, dict) else {}
                from_block = narrative.get("from_block_id")
                mapped_from = _map_block(from_block) if from_block is not None else None
                if from_block is not None and mapped_from == from_block:
                    raise PersistenceError(
                        f"chapter {chapter_index} reading unit {local_block!r} inherits "
                        f"from unknown block {from_block!r}"
                    )
                mapped_event_refs: list[str] = []
                for ref in narrative.get("event_refs") or []:
                    mapped = _map_reading(ref)
                    if not isinstance(mapped, str) or mapped not in event_ids:
                        raise PersistenceError(
                            f"chapter {chapter_index} reading unit time ref {ref!r} "
                            "does not resolve to an event of this revision"
                        )
                    mapped_event_refs.append(mapped)
                mapped_current_refs: list[str] = []
                for ref in unit.get("current_event_refs") or []:
                    mapped = _map_reading(ref)
                    if not isinstance(mapped, str) or mapped not in event_ids:
                        raise PersistenceError(
                            f"chapter {chapter_index} reading unit current ref {ref!r} "
                            "does not resolve to an event of this revision"
                        )
                    mapped_current_refs.append(mapped)
                resolved_spans: list[dict[str, Any]] = []
                for span in unit.get("resolved_spans") or []:
                    if not isinstance(span, dict):
                        continue
                    out_span = copy.deepcopy(span)
                    target = span.get("target_ref")
                    mapped_target = _map_reading(target) if target is not None else None
                    if target is not None and (
                        not isinstance(mapped_target, str) or mapped_target not in event_ids
                    ):
                        raise PersistenceError(
                            f"chapter {chapter_index} reading span {span.get('span_id')!r} "
                            f"references unknown event {target!r}"
                        )
                    out_span["target_ref"] = mapped_target
                    mapped_candidates: list[str] = []
                    for ref in span.get("candidate_refs") or []:
                        mapped = _map_reading(ref)
                        if not isinstance(mapped, str) or mapped not in event_ids:
                            raise PersistenceError(
                                f"chapter {chapter_index} reading span "
                                f"{span.get('span_id')!r} candidate {ref!r} is unknown"
                            )
                        mapped_candidates.append(mapped)
                    out_span["candidate_refs"] = mapped_candidates
                    resolved_spans.append(out_span)
                context_entities: list[dict[str, Any]] = []
                for context in unit.get("context_entities") or []:
                    if not isinstance(context, dict):
                        continue
                    entity_ref = context.get("entity_ref")
                    mapped_entity = _map_reading(entity_ref)
                    if not isinstance(mapped_entity, str) or mapped_entity not in entity_ids:
                        raise PersistenceError(
                            f"chapter {chapter_index} reading context references unknown "
                            f"entity {entity_ref!r}"
                        )
                    roles: list[dict[str, Any]] = []
                    for role in context.get("event_roles") or []:
                        if not isinstance(role, dict):
                            continue
                        event_ref = role.get("event_ref")
                        mapped_event = _map_reading(event_ref)
                        if not isinstance(mapped_event, str) or mapped_event not in event_ids:
                            raise PersistenceError(
                                f"chapter {chapter_index} reading context role references "
                                f"unknown event {event_ref!r}"
                            )
                        role = dict(role)
                        role["event_ref"] = mapped_event
                        roles.append(role)
                    context_entities.append(
                        {
                            "entity_ref": mapped_entity,
                            "importance": context.get("importance"),
                            "event_roles": roles,
                        }
                    )
                assembled_reading_units.append(
                    {
                        "unit_id": unit.get("unit_id"),
                        "chapter_id": chapter_id,
                        "chapter_index": chapter_index,
                        "artifact_sha256": item["artifact_sha256"],
                        "block_id": revision_block,
                        "chapter_block_id": local_block,
                        "text_hash": unit.get("text_hash"),
                        "narrative_time": {
                            "mode": narrative.get("mode"),
                            "event_refs": mapped_event_refs,
                            "from_block_id": mapped_from,
                            "source_selections": copy.deepcopy(
                                narrative.get("source_selections") or []
                            ),
                        },
                        "current_event_refs": mapped_current_refs,
                        "resolved_spans": resolved_spans,
                        "context_entities": context_entities,
                    }
                )

    # Source order is preserved: chapters are processed in chapter_index
    # order and blocks in the chapter's own translation order. Re-sorting by
    # the generated block ID would both reorder non-standard source IDs and
    # hide collisions behind a canonical-looking order.
    out_mentions.sort(key=lambda m: (m["chapter_index"], m["mention_id"]))
    out_record_sources.sort(key=lambda e: (e["record_ref"], e["chapter_index"]))
    merged_anchors.sort(
        key=lambda a: (str(a.get("chapter_id")), int(a.get("start", 0)), int(a.get("end", 0)), str(a.get("anchor_id")))
    )

    # -- person-state evidence into the same revision namespace (C2-R3-T03) ----
    # The current ``person_states`` block reuses this exact ``(chapter_index,
    # local_ref) -> revision_ref`` map for its entity/event/Claim refs, while
    # its phase/fact/order/continuity/disagreement local IDs receive a
    # chapter-bound namespace so the same local ``pf_001`` in two chapters can
    # never collide. Assembly never assigns a canonical ID and never links
    # same-name records; it only lifts and preserves their origin evidence.
    assembled_person_states: dict[str, Any] = {
        name: [] for name in _person_state_assembly.STATE_COLLECTIONS
    }
    person_state_evidence: list[dict[str, Any]] = []
    person_state_report: dict[str, Any] | None = None
    if person_state_path:
        state_result = _person_state_assembly.assemble_person_state_evidence(
            artifacts=ordered,
            chapter_index_by_id={
                chapter["chapter_id"]: chapter["chapter_index"]
                for chapter in plan_chapters
            },
            ref_map=id_map,
            block_map=block_id_map,
            entity_ids=entity_ids,
            event_ids=event_ids,
            claim_ids=claim_ids,
        )
        assembled_person_states = state_result["person_states"]
        person_state_evidence = state_result["evidence_manifests"]
        person_state_report = state_result["report"]
        if len(person_state_evidence) != len(ordered) or any(
            not isinstance(manifest, dict)
            or manifest.get("schema") != "chronicle.person-state-evidence-manifest"
            or manifest.get("version") != "0.1"
            or not isinstance(manifest.get("items"), list)
            for manifest in person_state_evidence
        ):
            raise PersistenceError(
                "current assembly requires one complete person-state evidence "
                "manifest per accepted chapter"
            )
        # One revision-local map: state local IDs join the same report map as
        # the entity/event/Claim refs so downstream review/compile can resolve
        # every origin ref.
        local_to_revision.update(state_result["local_to_revision"])

    # -- closed references across types (fail closed) ---------------------------
    for block in translation_blocks:
        for ref in block.get("entity_refs") or []:
            if ref.get("ref") not in entity_ids:
                raise PersistenceError(
                    f"translation block {block['block_id']!r} references missing entity {ref.get('ref')!r}"
                )
        for ref in block.get("event_refs") or []:
            if ref.get("ref") not in event_ids:
                raise PersistenceError(
                    f"translation block {block['block_id']!r} references missing event {ref.get('ref')!r}"
                )
    for mention in out_mentions:
        for ref in ([mention.get("target_ref")] if mention.get("target_ref") else []) + list(
            mention.get("candidate_refs") or []
        ):
            if ref not in entity_ids:
                raise PersistenceError(
                    f"mention {mention['mention_id']!r} references missing entity {ref!r}"
                )
    for event in final_events:
        for participant in event.get("participants") or []:
            if isinstance(participant, dict) and participant.get("entity_ref") not in entity_ids:
                raise PersistenceError(
                    f"event {event['temp_id']!r} references missing entity {participant.get('entity_ref')!r}"
                )
        for ref in event.get("places") or []:
            if ref not in entity_ids:
                raise PersistenceError(
                    f"event {event['temp_id']!r} references missing place entity {ref!r}"
                )
        parent = event.get("parent_event_ref")
        if parent is not None and parent not in event_ids:
            raise PersistenceError(
                f"event {event['temp_id']!r} references missing parent event {parent!r}"
            )
    for claim in final_claims:
        for field in ("subject", "object"):
            ref = claim.get(field)
            if ref is None:
                continue
            if isinstance(ref, dict):
                kind, target = ref.get("kind"), ref.get("ref")
                if kind in ("entity", "entity_ref") and target not in entity_ids:
                    raise PersistenceError(
                        f"claim {claim['temp_id']!r}.{field} references missing entity {target!r}"
                    )
                if kind in ("event", "event_ref") and target not in event_ids:
                    raise PersistenceError(
                        f"claim {claim['temp_id']!r}.{field} references missing event {target!r}"
                    )
    surviving = {r["temp_id"] for r in [*final_entities, *final_events, *final_claims]}
    for entry in out_record_sources:
        if entry["record_ref"] not in surviving:
            raise PersistenceError(
                f"record_sources entry references unknown record {entry['record_ref']!r}"
            )

    # -- warnings: bundle + candidate warnings, refs remapped, deduplicated ----
    warnings: list[dict[str, Any]] = []
    seen_warnings: set[str] = set()

    def _warn(warning: dict[str, Any], chapter_index: int) -> None:
        warning = copy.deepcopy(warning)
        refs = []
        for ref in warning.get("refs") or []:
            mapped = id_map.get((chapter_index, ref))
            if mapped is not None:
                refs.append(mapped)
        if refs or "refs" not in warning:
            if refs:
                warning["refs"] = refs
            elif "refs" in warning:
                del warning["refs"]
        elif "refs" in warning:
            del warning["refs"]
        key = canonical_json_bytes(warning).decode("utf-8")
        if key not in seen_warnings:
            seen_warnings.add(key)
            warnings.append(warning)

    for item in ordered:
        chapter_index = plan_by_id[item["chapter_id"]]["chapter_index"]
        for warning in (item["bundle"].get("warnings") or []):
            if isinstance(warning, dict):
                _warn(warning, chapter_index)
        for warning in (item["candidate"].get("warnings") or []):
            if isinstance(warning, dict):
                _warn(warning, chapter_index)
    warnings.sort(
        key=lambda w: (
            str(w.get("type") or ""),
            str(w.get("message") or ""),
            canonical_json_bytes(w.get("refs") or []).decode("utf-8"),
        )
    )

    bundle = {
        "schema_version": SCHEMA_VERSION,
        "source": merged_source,
        "entities": final_entities,
        "events": final_events,
        "claims": final_claims,
        "warnings": warnings,
    }
    validate_assembled_bundle(bundle)

    for item in ordered:
        chapter_id = item["chapter_id"]
        chapter_index = plan_by_id[chapter_id]["chapter_index"]
        chapter_artifacts[chapter_id] = item["artifact_sha256"]
        for record in [item["source"], *item["entities"], *item["events"], *item["claims"]]:
            old = record.get("temp_id")
            new = id_map.get((chapter_index, old)) if isinstance(old, str) else None
            if new is None or new == "src_001":
                continue
            provenance[new] = {
                "chapter_id": chapter_id,
                "chapter_index": chapter_index,
                "chapter_temp_id": old,
                "artifact_sha256": item["artifact_sha256"],
                "candidate_sha256": item["candidate_sha256"],
                "request_fingerprint": item["request_fingerprint"],
                "revision_id": revision_id,
                "source_sha256": source_sha256,
            }
    provenance["src_001"] = {
        "chapter_id": None,
        "chapter_index": None,
        "chapter_temp_id": None,
        "artifact_sha256": None,
        "candidate_sha256": None,
        "request_fingerprint": None,
        "revision_id": revision_id,
        "source_sha256": source_sha256,
        "merged_from_chapters": sorted(plan_by_id[c]["chapter_index"] for c in expected_ids),
        "merged_source_titles": titles,
    }

    counts_in = {
        "chapters": len(ordered),
        "entities": sum(len(item["entities"]) for item in ordered),
        "events": sum(len(item["events"]) for item in ordered),
        "claims": sum(len(item["claims"]) for item in ordered),
        "translation_blocks": sum(len(item["translation"].get("blocks") or []) for item in ordered),
        "mentions": sum(len(item["mentions"]) for item in ordered),
        "record_sources": sum(len(item["record_sources"]) for item in ordered),
        "anchors": sum(len(item["anchors"]) for item in ordered),
        "reading_units": sum(len(item["reading_units"]) for item in ordered),
    }
    report = {
        "schema": CHAPTER_REPORT_SCHEMA,
        "version": CHAPTER_REPORT_VERSION,
        "assembly_version": CHAPTER_ASSEMBLY_VERSION,
        "contract_version": CONTRACT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "candidate_schema": CHAPTER_CANDIDATE_SCHEMA,
        "candidate_version": CHAPTER_CANDIDATE_VERSION,
        "plan_version": CHAPTER_PLAN_VERSION,
        "revision": {
            "revision_id": revision_id,
            "source_sha256": source_sha256,
            "normalized_sha256": normalized_sha256,
        },
        "plan": {
            "plan_sha256": chapter_plan.get("plan_sha256"),
            "chapter_count": len(plan_chapters),
            "chapters": [
                {
                    "chapter_id": c["chapter_id"],
                    "chapter_index": c["chapter_index"],
                    "title": c.get("title"),
                    "start": c.get("start"),
                    "end": c.get("end"),
                }
                for c in plan_chapters
            ],
        },
        "inputs": [
            {
                "chapter_id": item["chapter_id"],
                "chapter_index": plan_by_id[item["chapter_id"]]["chapter_index"],
                "artifact_sha256": item["artifact_sha256"],
                "candidate_sha256": item["candidate_sha256"],
                "request_fingerprint": item["request_fingerprint"],
                "counts": {
                    "entities": len(item["entities"]),
                    "events": len(item["events"]),
                    "claims": len(item["claims"]),
                    "translation_blocks": len(item["translation"].get("blocks") or []),
                    "mentions": len(item["mentions"]),
                    "record_sources": len(item["record_sources"]),
                    "anchors": len(item["anchors"]),
                    "reading_units": len(item["reading_units"]),
                },
            }
            for item in ordered
        ],
        "counts": {
            "in": counts_in,
            "out": {
                "entities": len(final_entities),
                "events": len(final_events),
                "claims": len(final_claims),
                "translation_blocks": len(translation_blocks),
                "mentions": len(out_mentions),
                "record_sources": len(out_record_sources),
                "anchors": len(merged_anchors),
                "warnings": len(warnings),
                "reading_units": len(assembled_reading_units),
                "person_states": len(person_state_evidence),
                "person_state_items": sum(
                    len(manifest.get("items") or []) for manifest in person_state_evidence
                ),
            },
        },
        "person_state": person_state_report,
        "chapter_by_ref": dict(sorted(chapter_by_ref.items())),
        "local_to_revision": dict(sorted(local_to_revision.items())),
        "chapter_artifacts": dict(sorted(chapter_artifacts.items())),
        "record_provenance": dict(sorted(provenance.items())),
        "merged_source_titles": titles,
        "bundle_sha256": sha256_json(bundle),
        "authoritative": False,
        "authority_note": NON_AUTHORITATIVE_NOTE,
    }

    return {
        "bundle": bundle,
        "translation_blocks": translation_blocks,
        "mentions": out_mentions,
        "record_sources": out_record_sources,
        "anchors": merged_anchors,
        "reading_units": assembled_reading_units,
        "person_states": assembled_person_states,
        "person_state_evidence": person_state_evidence,
        "report": report,
    }
