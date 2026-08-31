"""Model-backed extraction support for the Chronicle v0.1 prototype.

The provider boundary is deliberately vendor-neutral. A provider receives one
closed-book extraction prompt and returns text containing exactly one JSON
object. The command adapter makes the prototype usable with any local or remote
model client that can read stdin and write stdout.
"""

from __future__ import annotations

import copy
import json
import shlex
import subprocess
from pathlib import Path
from typing import Any, Protocol


class ModelV0Error(RuntimeError):
    pass


class ModelProvider(Protocol):
    name: str

    def complete(self, prompt: str) -> str:
        """Return the model response text for a prompt."""


class CommandModelProvider:
    """Invoke an external model client without using a shell.

    The prompt is written to stdin. The provider command must write the model
    response to stdout and return exit status 0.
    """

    def __init__(self, command: str | list[str], timeout_seconds: int = 180):
        argv = shlex.split(command) if isinstance(command, str) else list(command)
        if not argv:
            raise ModelV0Error("model command must not be empty")
        self.argv = argv
        self.timeout_seconds = timeout_seconds
        self.name = f"command:{argv[0]}"

    def complete(self, prompt: str) -> str:
        try:
            result = subprocess.run(
                self.argv,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ModelV0Error(f"model command was not found: {self.argv[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ModelV0Error(
                f"model command exceeded {self.timeout_seconds}s timeout"
            ) from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or "no stderr"
            raise ModelV0Error(
                f"model command exited with {result.returncode}: {detail}"
            )
        if not result.stdout.strip():
            raise ModelV0Error("model command returned empty stdout")
        return result.stdout


class ReplayModelProvider:
    """Replay a previously captured model response for offline evaluation."""

    def __init__(self, response_path: Path):
        self.response_path = response_path
        self.name = f"replay:{response_path.name}"

    def complete(self, prompt: str) -> str:  # noqa: ARG002 - protocol compatibility
        return self.response_path.read_text(encoding="utf-8")


def build_model_prompt(
    raw: str,
    context: dict[str, Any],
    config: dict[str, Any],
    schema: dict[str, Any],
) -> str:
    """Build a closed-book extraction prompt.

    Gold/reference output is intentionally not accepted by this API, which
    keeps `expected.yaml` structurally outside the model-input path.
    """

    context_text = json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True)
    config_text = json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True)
    schema_text = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True)
    return f"""You are Chronicle model-v0, a source-grounded historical data extractor.

NON-NEGOTIABLE RULES
1. Treat SOURCE TEXT as a closed book. Extract only claims supported by that text plus explicit DOCUMENT CONTEXT.
2. Do not add facts from prior historical knowledge, even if you believe they are true.
3. Every Claim.evidence.text must be an exact substring of SOURCE TEXT. Do not paraphrase evidence.
4. Preserve traditional/regnal time expressions. You may use the supplied context's safe normalized year, but never convert a traditional month/day into a Gregorian month/day unless the context explicitly provides that verified conversion.
5. Use only job-local temp IDs (`src_###`, `ent_###`, `evt_###`, `clm_###`). Do not invent canonical UUIDs.
6. Entity resolution is deferred. If a mention is ambiguous, keep it unresolved and emit a warning rather than guessing.
7. Event and Claim are different layers: Event is a historical occurrence; Claim records what this source asserts about an entity/event.
8. Set every newly extracted Claim assessment to `unassessed`. Extraction confidence is not historical truth confidence.
9. Return one JSON object only. No prose, no Markdown fences unless your client cannot avoid them.
10. The JSON must satisfy the supplied Chronicle v0.1 JSON Schema.

DOCUMENT CONTEXT
{context_text}

INGESTION POLICY
{config_text}

OUTPUT JSON SCHEMA
{schema_text}

SOURCE TEXT
---BEGIN SOURCE---
{raw}
---END SOURCE---
"""


def parse_model_response(text: str) -> dict[str, Any]:
    """Parse plain JSON or one Markdown-fenced JSON object."""

    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) < 3 or not lines[-1].strip().startswith("```"):
            raise ModelV0Error("model response has an unterminated Markdown fence")
        first = lines[0].strip().lower()
        if first not in {"```", "```json", "```jsonc"}:
            raise ModelV0Error(f"unsupported model response fence: {lines[0].strip()}")
        stripped = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ModelV0Error(
            f"model response is not valid JSON at line {exc.lineno} column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(value, dict):
        raise ModelV0Error("model response must be one JSON object")
    return value


def _identity_key(item: dict[str, Any], fallback: str) -> str:
    value = item.get("temp_id") or item.get("id")
    return str(value) if value else fallback


def _model_extraction(existing: Any, job_id: str) -> dict[str, Any]:
    confidence = existing.get("confidence") if isinstance(existing, dict) else None
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        confidence = None
    return {"method": "model", "job_id": job_id, "confidence": confidence}


def normalize_model_bundle(
    value: dict[str, Any], fixture_name: str, job_id: str = "model-v0"
) -> dict[str, Any]:
    """Normalize model transport details without inventing historical facts.

    Temp IDs and extraction diagnostics are transport metadata, so they are
    normalized deterministically. Historical content is otherwise left alone
    and must pass the Chronicle JSON Schema on its own merits.
    """

    bundle = copy.deepcopy(value)
    bundle.setdefault("schema_version", "0.1")
    bundle.setdefault("warnings", [])

    source = bundle.get("source")
    source_map: dict[str, str] = {}
    if isinstance(source, dict):
        old = _identity_key(source, "src_001")
        source_map[old] = "src_001"
        source.pop("id", None)
        source["temp_id"] = "src_001"
        source["extraction"] = _model_extraction(source.get("extraction"), job_id)
        metadata = source.get("metadata")
        if isinstance(metadata, dict):
            metadata.setdefault("fixture", fixture_name)

    entity_map: dict[str, str] = {}
    entities = bundle.get("entities")
    if isinstance(entities, list):
        for index, entity in enumerate(entities, 1):
            if not isinstance(entity, dict):
                continue
            old = _identity_key(entity, f"__entity_{index}")
            new = f"ent_{index:03d}"
            entity_map[old] = new
            entity.pop("id", None)
            entity["temp_id"] = new
            entity["extraction"] = _model_extraction(entity.get("extraction"), job_id)
            entity.setdefault("resolution", {"status": "unresolved"})

    event_map: dict[str, str] = {}
    events = bundle.get("events")
    if isinstance(events, list):
        for index, event in enumerate(events, 1):
            if not isinstance(event, dict):
                continue
            old = _identity_key(event, f"__event_{index}")
            new = f"evt_{index:03d}"
            event_map[old] = new
            event.pop("id", None)
            event["temp_id"] = new
            event["extraction"] = _model_extraction(event.get("extraction"), job_id)

    claims = bundle.get("claims")
    if isinstance(claims, list):
        for index, claim in enumerate(claims, 1):
            if not isinstance(claim, dict):
                continue
            claim.pop("id", None)
            claim["temp_id"] = f"clm_{index:03d}"
            claim["extraction"] = _model_extraction(claim.get("extraction"), job_id)
            claim.setdefault("assessment", {"status": "unassessed"})

    def rewrite_ref(ref: Any) -> Any:
        if not isinstance(ref, str):
            return ref
        if ref in entity_map:
            return entity_map[ref]
        if ref in event_map:
            return event_map[ref]
        if ref in source_map:
            return source_map[ref]
        return ref

    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            participants = event.get("participants")
            if isinstance(participants, list):
                for participant in participants:
                    if isinstance(participant, dict) and "entity_ref" in participant:
                        participant["entity_ref"] = rewrite_ref(participant["entity_ref"])
            places = event.get("places")
            if isinstance(places, list):
                event["places"] = [rewrite_ref(ref) for ref in places]
            if event.get("parent_event_ref") is not None:
                event["parent_event_ref"] = rewrite_ref(event["parent_event_ref"])

    if isinstance(claims, list):
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            for field in ("subject", "object"):
                ref = claim.get(field)
                if isinstance(ref, dict) and ref.get("kind") in {
                    "entity_ref",
                    "event_ref",
                }:
                    ref["ref"] = rewrite_ref(ref.get("ref"))
            evidence = claim.get("evidence")
            if isinstance(evidence, dict) and "source_ref" in evidence:
                evidence["source_ref"] = rewrite_ref(evidence["source_ref"])
                locator = evidence.get("locator")
                if isinstance(locator, dict):
                    locator.setdefault("fixture", fixture_name)

    warnings = bundle.get("warnings")
    if isinstance(warnings, list):
        for warning in warnings:
            if isinstance(warning, dict) and isinstance(warning.get("refs"), list):
                warning["refs"] = [rewrite_ref(ref) for ref in warning["refs"]]

    return bundle


class ModelV0Extractor:
    def __init__(
        self,
        raw: str,
        context: dict[str, Any],
        config: dict[str, Any],
        schema: dict[str, Any],
        fixture_name: str,
        provider: ModelProvider,
    ):
        self.raw = raw
        self.context = context
        self.config = config
        self.schema = schema
        self.fixture_name = fixture_name
        self.provider = provider

    def prompt(self) -> str:
        return build_model_prompt(self.raw, self.context, self.config, self.schema)

    def extract(self) -> dict[str, Any]:
        response = self.provider.complete(self.prompt())
        parsed = parse_model_response(response)
        return normalize_model_bundle(parsed, self.fixture_name)


def _strip_identity(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_identity(child)
            for key, child in value.items()
            if key not in {"temp_id", "id", "extraction", "warnings"}
        }
    if isinstance(value, list):
        return [_strip_identity(child) for child in value]
    return value


def _labels(bundle: dict[str, Any]) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    entities: dict[str, str] = {}
    for item in bundle.get("entities", []):
        if isinstance(item, dict) and item.get("canonical_name"):
            identity = item.get("temp_id") or item.get("id")
            if identity:
                entities[str(identity)] = str(item["canonical_name"])
    events: dict[str, str] = {}
    for item in bundle.get("events", []):
        if isinstance(item, dict) and item.get("title"):
            identity = item.get("temp_id") or item.get("id")
            if identity:
                events[str(identity)] = str(item["title"])
    sources: dict[str, str] = {}
    source = bundle.get("source")
    if isinstance(source, dict) and source.get("title"):
        identity = source.get("temp_id") or source.get("id")
        if identity:
            sources[str(identity)] = str(source["title"])
    return entities, events, sources


def _resolved(
    value: Any,
    entity_labels: dict[str, str],
    event_labels: dict[str, str],
    source_labels: dict[str, str],
) -> Any:
    if isinstance(value, dict):
        if value.get("kind") == "entity_ref" and isinstance(value.get("ref"), str):
            return {"kind": "entity_ref", "ref": entity_labels.get(value["ref"], value["ref"])}
        if value.get("kind") == "event_ref" and isinstance(value.get("ref"), str):
            return {"kind": "event_ref", "ref": event_labels.get(value["ref"], value["ref"])}
        result = {}
        for key, child in value.items():
            if key in {"temp_id", "id", "extraction", "warnings"}:
                continue
            if key == "entity_ref" and isinstance(child, str):
                result[key] = entity_labels.get(child, child)
            elif key == "parent_event_ref" and isinstance(child, str):
                result[key] = event_labels.get(child, child)
            elif key == "source_ref" and isinstance(child, str):
                result[key] = source_labels.get(child, child)
            elif key == "places" and isinstance(child, list):
                result[key] = [entity_labels.get(str(ref), ref) for ref in child]
            else:
                result[key] = _resolved(child, entity_labels, event_labels, source_labels)
        return result
    if isinstance(value, list):
        return [_resolved(child, entity_labels, event_labels, source_labels) for child in value]
    return value


def semantic_projection(bundle: dict[str, Any]) -> dict[str, Any]:
    """Build an ID/order-transport-independent projection for model evaluation."""

    entity_labels, event_labels, source_labels = _labels(bundle)
    source = _strip_identity(bundle.get("source"))
    entities = {}
    for item in bundle.get("entities", []):
        if isinstance(item, dict) and item.get("canonical_name"):
            entities[str(item["canonical_name"])] = _resolved(
                item, entity_labels, event_labels, source_labels
            )
    events = {}
    for item in bundle.get("events", []):
        if isinstance(item, dict) and item.get("title"):
            events[str(item["title"])] = _resolved(
                item, entity_labels, event_labels, source_labels
            )
    claims = {}
    for item in bundle.get("claims", []):
        if not isinstance(item, dict):
            continue
        resolved = _resolved(item, entity_labels, event_labels, source_labels)
        identity = {
            "subject": resolved.get("subject"),
            "predicate": resolved.get("predicate"),
            "object": resolved.get("object"),
            "evidence": (resolved.get("evidence") or {}).get("text"),
        }
        key = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        claims[key] = resolved
    return {"source": source, "entities": entities, "events": events, "claims": claims}


def compare_model_bundle(actual: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    left = semantic_projection(actual)
    right = semantic_projection(expected)
    mismatches: list[str] = []
    if left["source"] != right["source"]:
        mismatches.append("source differs from human gold")
    for collection in ("entities", "events", "claims"):
        actual_items = left[collection]
        expected_items = right[collection]
        for key in sorted(expected_items.keys() - actual_items.keys()):
            mismatches.append(f"{collection}: missing {key}")
        for key in sorted(actual_items.keys() - expected_items.keys()):
            mismatches.append(f"{collection}: unexpected {key}")
        for key in sorted(actual_items.keys() & expected_items.keys()):
            if actual_items[key] != expected_items[key]:
                mismatches.append(f"{collection}: {key} differs")
    return mismatches


def evaluation_report(
    bundle: dict[str, Any],
    extractor: str,
    provider: str | None,
    schema_errors: list[str],
    gold_mismatches: list[str] | None,
) -> dict[str, Any]:
    counts = {}
    for collection in ("entities", "events", "claims", "warnings"):
        value = bundle.get(collection)
        counts[collection] = len(value) if isinstance(value, list) else None
    return {
        "schema": "chronicle.ingestion-evaluation",
        "version": "0.1",
        "extractor": extractor,
        "provider": provider,
        "counts": counts,
        "schema_validation": {"passed": not schema_errors, "errors": schema_errors},
        "gold_comparison": {
            "performed": gold_mismatches is not None,
            "passed": gold_mismatches == [] if gold_mismatches is not None else None,
            "mismatch_count": len(gold_mismatches) if gold_mismatches is not None else None,
            "mismatches": gold_mismatches,
        },
    }
