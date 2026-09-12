"""Chronicle C2-R1-T05 whole-chapter joint translation/extraction (application-owned).

Pure deterministic orchestration for one complete natural chapter, per
``chapter-production.md`` sections 3-4: render the whole chapter,
call the model through the ``model.complete(prompt) -> str`` boundary,
validate with the T01 contract validator, and allow at most one whole-
chapter correction re-ask. No database, network, or real-provider access
(Amendment 0006); no worker changes. Transport retries belong to T06 and
are counted separately from the single semantic correction round here.

Result shape of :func:`extract_chapter`::

    {
      "accepted": bool,
      "artifact": dict | None,          # chronicle.chapter-artifact / 0.1
      "attempts": [...],                # one entry per model call, each with
                                        # prompt/response sizes+hashes,
                                        # validation report, and latency_ms
      "error": None | {"code": str, "message": str},
      "request_fingerprint": str,
      "fingerprints": {...},            # limits/model/schema/source/plan binding
      "correction_rounds_used": 0 | 1,
      "transport_retries": 0,           # always 0 here; T06 owns transport
    }

Typed failure codes (``error.code``): ``missing_model``,
``invalid_request``, ``source_over_limit``, ``prompt_over_limit``,
``correction_prompt_over_limit``, ``response_over_limit_chars``,
``response_over_limit_bytes``, ``response_empty``, ``response_parse``,
``model_transport_error``, ``validation_failed``.

Oversized prompts, oversized responses, and transport failures fail
closed immediately: nothing is truncated, and there is no fallback to
chunked production. A failed extraction records its attempts instead of
manufacturing a valid-looking result.

Validation reports here are mechanical only. A passing report proves
contract shape (coverage, references, anchors, time precision, alias
discipline) — it is never presented as content-accuracy evidence.
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
from typing import Any, Protocol

import chapter_contract as C
import chapter_prompt as P
from common import PersistenceError

try:
    import reading_contract as R
except ImportError:  # pragma: no cover - package import path
    from . import reading_contract as R  # type: ignore[no-redef]

try:
    import person_state_contract as PS
except ImportError:  # pragma: no cover - package import path
    from . import person_state_contract as PS  # type: ignore[no-redef]

#: Version of this whole-chapter extraction pipeline step. The 0.1 path is
#: frozen; 0.2 adds reading annotations; 0.3 adds person states and is the
#: registered production generation.
EXTRACTION_VERSION = "c2r1-extraction-v1"
READING_EXTRACTION_VERSION = "c2r2-extraction-v2"
PERSON_STATE_EXTRACTION_VERSION = "c2r3-extraction-v2"

#: Versioned, replayable restriction on metadata-only correction rounds.
#: This is an extraction check, not a replacement candidate validator or
#: evidence that a structurally valid translation is semantically complete.
CORRECTION_POLICY_VERSION = "c2-chapter-correction-v1"

# Historical prompt generations must stay explicit: changing a current
# fingerprint to v1 cannot turn a new protected run into a legacy run.
_HISTORY_PROMPT_VERSIONS = {
    ("0.2", "c2r2-extraction-v1", None): {
        f"c2r2-chapter-prompt-v{i}" for i in range(1, 5)
    },
    ("0.3", "c2r3-extraction-v1", None): {
        "c2r3-chapter-prompt-v1", "c2r3-chapter-prompt-v2",
    },
    ("0.2", "c2r2-extraction-v2", CORRECTION_POLICY_VERSION): {"c2r2-chapter-prompt-v5"},
    ("0.3", "c2r3-extraction-v2", CORRECTION_POLICY_VERSION): {"c2r3-chapter-prompt-v3"},
}

#: Prompt template version bound into every attempt and producing run.
PROMPT_VERSION = P.PROMPT_VERSION

#: Model-generatable candidate marker accepted here (T01 contract).
CANDIDATE_SCHEMA = P.CANDIDATE_SCHEMA
CANDIDATE_VERSION = P.CANDIDATE_VERSION

#: Reading candidate marker (second round).
READING_CANDIDATE_VERSION = P.READING_CANDIDATE_VERSION

#: Person-state candidate marker (third round, registered production).
PERSON_STATE_CANDIDATE_VERSION = P.PERSON_STATE_CANDIDATE_VERSION

#: Transport-retry ownership marker: this layer never retries transport.
TRANSPORT_RETRIES_HERE = 0


def prompt_version_for(candidate_version: str) -> str:
    return P.prompt_version_for(candidate_version)


def request_candidate_version(request: dict[str, Any]) -> str:
    return P.request_candidate_version(request)


class ChapterModelProvider(Protocol):
    """Vendor-neutral model boundary for one whole-chapter request."""

    name: str

    def complete(self, prompt: str) -> str:
        """Return the raw model response text for a prompt."""


class ChapterModelError(RuntimeError):
    """Raised when a model response cannot be parsed."""


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _limits_for(request: dict[str, Any], limits: C.ChapterLimits | None) -> C.ChapterLimits:
    if limits is not None:
        if not isinstance(limits, C.ChapterLimits):
            raise PersistenceError("limits must be a ChapterLimits")
        return limits
    return C.ChapterLimits.from_dict(request.get("limits"))


def _model_name(model: Any) -> str:
    name = getattr(model, "name", None)
    if not isinstance(name, str) or not name:
        return "unknown-model"
    return name


def fingerprints_for(
    request: dict[str, Any],
    *,
    model_name: str,
    limits: C.ChapterLimits,
    candidate_version: str | None = None,
) -> dict[str, Any]:
    """Bind limits/model/schema/source/plan versions for one execution.

    ``candidate_version`` selects which contract/prompt/limits binding is
    recorded so 0.1 and 0.2 runs stay distinguishable in run history.
    """
    version = candidate_version or C.PRODUCTION_CANDIDATE_VERSION
    prompt_version = prompt_version_for(version)
    if version == PERSON_STATE_CANDIDATE_VERSION:
        extraction_version = PERSON_STATE_EXTRACTION_VERSION
    elif version == READING_CANDIDATE_VERSION:
        extraction_version = READING_EXTRACTION_VERSION
    else:
        extraction_version = EXTRACTION_VERSION
    fingerprints = {
        "request_fingerprint": C.request_fingerprint(request),
        "limits": limits.to_dict(),
        "model": model_name,
        "prompt_version": prompt_version,
        "extraction_version": extraction_version,
        "candidate_schema": f"{CANDIDATE_SCHEMA}/{version}",
        "source_sha256": request.get("source_sha256"),
        "normalized_sha256": request.get("normalized_sha256"),
        "plan_version": request.get("plan_version"),
        "chapter_id": request.get("chapter_id"),
    }
    if version in (READING_CANDIDATE_VERSION, PERSON_STATE_CANDIDATE_VERSION):
        fingerprints["reading_schema"] = f"{R.READING_SCHEMA}/{R.READING_VERSION}"
        fingerprints["reading_limits"] = R.ReadingLimits().to_dict()
        fingerprints["correction_policy_version"] = CORRECTION_POLICY_VERSION
    if version == PERSON_STATE_CANDIDATE_VERSION:
        fingerprints["person_state_schema"] = (
            f"{PS.PERSON_STATE_SCHEMA}/{PS.PERSON_STATE_VERSION}"
        )
        fingerprints["person_state_contract"] = PS.CONTRACT_VERSION
        fingerprints["person_state_limits"] = PS.PersonStateLimits().to_dict()
    return fingerprints


def _validate_candidate(
    request: dict[str, Any], candidate: dict[str, Any], *, candidate_version: str
) -> dict[str, Any]:
    """Dispatch acceptance validation to the registered version owner.

    0.1 stays with the frozen first-round ``chapter_contract`` validator;
    0.2 is consumed only through the T01 ``reading_contract`` validator;
    0.3 is consumed only through the T01 ``person_state_contract`` validator
    (which itself reuses the frozen 0.2 reading validator on the subset), so
    no second set of reading/person-state checks exists.
    """
    if candidate_version == PERSON_STATE_CANDIDATE_VERSION:
        return PS.validate_person_state_candidate(request, candidate)
    if candidate_version == READING_CANDIDATE_VERSION:
        return R.validate_reading_annotations(request, candidate)
    return C.validate_chapter_candidate(request, candidate)


def _accept_candidate(
    request: dict[str, Any],
    candidate: dict[str, Any],
    *,
    candidate_version: str,
    producing_run: dict[str, Any],
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if candidate_version == PERSON_STATE_CANDIDATE_VERSION:
        return PS.accept_person_state_candidate(
            request, candidate, producing_run=producing_run, report=report
        )
    if candidate_version == READING_CANDIDATE_VERSION:
        return R.accept_reading_candidate(
            request, candidate, producing_run=producing_run, report=report
        )
    return C.accept_chapter_candidate(
        request, candidate, producing_run=producing_run, report=report
    )


def _flatten_report_errors(report: dict[str, Any]) -> list[str]:
    if report.get("schema") == "chronicle.person-state-validation":
        return PS.flatten_person_state_errors(report)
    if report.get("schema") == "chronicle.reading-validation":
        return R.flatten_reading_errors(report)
    return C.flatten_validation_errors(report)


def _error_categories(report: dict[str, Any]) -> dict[str, int]:
    """Count non-empty validation categories for consumer-side triage.

    Lets a consumer tell a missing reading unit, an overlapping span, a
    wrong current-time basis, a bad reference, etc. apart without
    re-parsing the free-form message.
    """
    categories = report.get("errors")
    if not isinstance(categories, dict):
        return {}
    return {
        str(name): len(messages)
        for name, messages in categories.items()
        if isinstance(messages, list) and messages
    }


def _translation_sequence(candidate: Any) -> list[tuple[str, str]] | None:
    """Return ordered prose only; references remain independently repairable."""
    translation = candidate.get("translation") if isinstance(candidate, dict) else None
    blocks = translation.get("blocks") if isinstance(translation, dict) else None
    if not isinstance(blocks, list) or not blocks:
        return None
    sequence: list[tuple[str, str]] = []
    seen: set[str] = set()
    for block in blocks:
        if not isinstance(block, dict):
            return None
        block_id, text = block.get("block_id"), block.get("text")
        if (
            not isinstance(block_id, str) or not block_id or block_id in seen
            or not isinstance(text, str) or not text.strip()
        ):
            return None
        seen.add(block_id)
        sequence.append((block_id, text))
    return sequence


def _preserve_translation(
    candidate: Any, report: Any, *, candidate_version: str
) -> bool:
    """Conservatively restrict repairs using the FULL, unabridged report.

    Schema, source coverage, identity, capacity and unknown failures may
    require prose/block changes, so they keep the existing whole-chapter
    repair. A duplicate translation block ID is a `references` failure;
    checking the sequence separately prevents freezing that invalid shape.
    The 0.3 report nests all 0.2 errors under `reading`.
    """
    report_schema = {
        READING_CANDIDATE_VERSION: "chronicle.reading-validation",
        PERSON_STATE_CANDIDATE_VERSION: "chronicle.person-state-validation",
    }.get(candidate_version)
    if (
        report_schema is None or not isinstance(report, dict)
        or report.get("schema") != report_schema or report.get("passed") is not False
        or _translation_sequence(candidate) is None
    ):
        return False
    categories = report.get("errors")
    if not isinstance(categories, dict) or any(
        not isinstance(messages, list) or any(not isinstance(m, str) for m in messages)
        for messages in categories.values()
    ):
        return False
    errors = _flatten_report_errors(report)
    if not errors:
        return False
    chapter_metadata = {
        "references", "record_sources", "mentions", "anchors", "time_precision", "aliases",
    }
    reading_metadata = {
        "reading_coverage", "reading_refs", "reading_time", "reading_spans",
        "reading_context", "canonical_id",
    }
    state_metadata = {
        "person_state_coverage", "person_state_refs", "person_state_phase",
        "person_state_types", "person_state_continuity", "canonical_id",
    }
    for error in errors:
        if candidate_version == PERSON_STATE_CANDIDATE_VERSION:
            category, _, message = error.partition(": ")
            if category in state_metadata and message and not message.startswith("request:"):
                continue
            if category != "reading":
                return False
            error = message
        category, _, message = error.partition(": ")
        if category == "chapter":
            category, _, message = message.partition(": ")
            allowed = chapter_metadata
        else:
            allowed = reading_metadata
        if category not in allowed or not message or message.startswith("request:"):
            return False
    return True


def _validate_correction(
    previous_candidate: Any,
    previous_report: Any,
    candidate: dict[str, Any],
    *,
    candidate_version: str,
) -> dict[str, Any]:
    """Shared generation/history check; never silently splice old prose back."""
    preserve = _preserve_translation(
        previous_candidate, previous_report, candidate_version=candidate_version,
    )
    errors: list[str] = []
    if preserve:
        previous = _translation_sequence(previous_candidate)
        assert previous is not None  # Established by _preserve_translation.
        current = _translation_sequence(candidate)
        if current is None:
            errors.append("translation.blocks lost valid, unique block IDs or non-empty text")
        else:
            if [block_id for block_id, _ in previous] != [block_id for block_id, _ in current]:
                errors.append("translation.blocks changed block IDs or order during metadata correction")
            current_by_id = dict(current)
            for block_id, text in previous:
                if block_id not in current_by_id:
                    errors.append(f"translation block {block_id!r} was removed during metadata correction")
                elif current_by_id[block_id] != text:
                    errors.append(f"translation block {block_id!r} text changed during metadata correction")
    return {
        "policy_version": CORRECTION_POLICY_VERSION,
        "mode": "preserve_translation" if preserve else "whole_chapter",
        "passed": not errors,
        "errors": errors,
    }


def parse_candidate_response(text: str) -> dict[str, Any]:
    """Parse plain JSON or one Markdown-fenced JSON object."""
    if not isinstance(text, str) or not text.strip():
        raise ChapterModelError("model response is empty")
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) < 3 or not lines[-1].strip().startswith("```"):
            raise ChapterModelError("model response has an unterminated Markdown fence")
        first = lines[0].strip().lower()
        if first not in {"```", "```json", "```jsonc"}:
            raise ChapterModelError(f"unsupported model response fence: {lines[0].strip()}")
        stripped = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ChapterModelError(
            f"model response is not valid JSON at line {exc.lineno} "
            f"column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(value, dict):
        raise ChapterModelError("model response must be one JSON object")
    return value


def flatten_validation_errors(report: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for category, messages in (report.get("errors") or {}).items():
        for message in messages or []:
            result.append(f"{category}: {message}")
    return result


def _attempt(
    *,
    kind: str,
    prompt: str | None,
    raw_response: str | None,
    parse_error: str | None = None,
    transport_error: str | None = None,
    validation: dict[str, Any] | None = None,
    candidate: dict[str, Any] | None = None,
    latency_ms: int | None = None,
    correction_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    attempt = {
        "kind": kind,
        "prompt": prompt,
        "prompt_chars": len(prompt) if isinstance(prompt, str) else None,
        "prompt_sha256": sha256_text(prompt) if isinstance(prompt, str) else None,
        "raw_response": raw_response,
        "raw_response_chars": len(raw_response) if isinstance(raw_response, str) else None,
        "raw_response_bytes": (
            len(raw_response.encode("utf-8")) if isinstance(raw_response, str) else None
        ),
        "raw_response_sha256": sha256_text(raw_response) if isinstance(raw_response, str) else None,
        "latency_ms": latency_ms,
        "parse_error": parse_error,
        "transport_error": transport_error,
        "validation": copy.deepcopy(validation),
        "candidate": copy.deepcopy(candidate),
    }
    if correction_validation is not None:
        attempt["correction_validation"] = copy.deepcopy(correction_validation)
    return attempt


def _failure(
    *,
    code: str,
    message: str,
    attempts: list[dict[str, Any]],
    request: dict[str, Any],
    model_name: str,
    limits: C.ChapterLimits,
    correction_rounds_used: int = 0,
    candidate_version: str | None = None,
) -> dict[str, Any]:
    fingerprints = None
    try:
        fingerprints = fingerprints_for(
            request, model_name=model_name, limits=limits,
            candidate_version=candidate_version,
        )
        fingerprint = fingerprints["request_fingerprint"]
    except Exception:  # fail closed even when the request itself is malformed
        fingerprints = {"request_fingerprint": None}
        fingerprint = None
    return {
        "accepted": False,
        "artifact": None,
        "attempts": attempts,
        "error": {"code": code, "message": message},
        "request_fingerprint": fingerprint,
        "fingerprints": fingerprints,
        "correction_rounds_used": correction_rounds_used,
        "transport_retries": TRANSPORT_RETRIES_HERE,
    }


def _producing_run(
    *,
    model_name: str,
    request_fingerprint: str,
    candidate_version: str | None = None,
) -> dict[str, Any]:
    version = candidate_version or C.PRODUCTION_CANDIDATE_VERSION
    prompt_version = prompt_version_for(version)
    digest = sha256_text(f"{request_fingerprint}|{model_name}|{prompt_version}")[:16]
    return {
        "run_id": f"chapter-extract-{digest}",
        "model": model_name,
        "prompt_schema_version": prompt_version,
    }


def extract_chapter(
    request: dict[str, Any],
    model: ChapterModelProvider | None,
    *,
    limits: C.ChapterLimits | None = None,
) -> dict[str, Any]:
    """Run whole-chapter joint translation/extraction; fail closed when invalid.

    At most two ``model.complete`` calls are ever made (initial + one
    whole-chapter correction). Transport failures are recorded, not
    retried here: HTTP/transport retry belongs to T06 and stays
    distinguishable from the semantic correction round.
    """
    if model is None or not callable(getattr(model, "complete", None)):
        fallback_limits = limits if isinstance(limits, C.ChapterLimits) else C.ChapterLimits()
        return _failure(
            code="missing_model",
            message="chapter extraction requires a model with complete(prompt)->str; refusing to fake success",
            attempts=[],
            request=request if isinstance(request, dict) else {},
            model_name="missing-model",
            limits=fallback_limits,
        )
    model_name = _model_name(model)

    if not isinstance(request, dict):
        return _failure(
            code="invalid_request",
            message="chapter request must be a JSON object",
            attempts=[],
            request={},
            model_name=model_name,
            limits=limits if isinstance(limits, C.ChapterLimits) else C.ChapterLimits(),
        )
    try:
        candidate_version = request_candidate_version(request)
    except PersistenceError as exc:
        return _failure(
            code="unsupported_candidate_version",
            message=str(exc),
            attempts=[],
            request=request,
            model_name=model_name,
            limits=limits if isinstance(limits, C.ChapterLimits) else C.ChapterLimits(),
        )
    try:
        active_limits = _limits_for(request, limits)
    except PersistenceError as exc:
        return _failure(
            code="invalid_request",
            message=f"chapter request limits are invalid: {exc}",
            attempts=[],
            request=request,
            model_name=model_name,
            limits=C.ChapterLimits(),
            candidate_version=candidate_version,
        )

    text = request.get("normalized_text")
    if not isinstance(text, str) or text == "":
        return _failure(
            code="invalid_request",
            message="chapter request normalized_text must be a non-empty string",
            attempts=[],
            request=request,
            model_name=model_name,
            limits=active_limits,
            candidate_version=candidate_version,
        )
    if len(text) > active_limits.max_source_chars:
        return _failure(
            code="source_over_limit",
            message=(
                f"chapter text ({len(text)} chars) exceeds max_source_chars "
                f"({active_limits.max_source_chars}); refusing to truncate or "
                "fall back to chunked production (fail closed)"
            ),
            attempts=[],
            request=request,
            model_name=model_name,
            limits=active_limits,
            candidate_version=candidate_version,
        )

    try:
        prompt = P.render_chapter_prompt(request)
    except PersistenceError as exc:
        return _failure(
            code="invalid_request",
            message=f"chapter request cannot be rendered: {exc}",
            attempts=[],
            request=request,
            model_name=model_name,
            limits=active_limits,
            candidate_version=candidate_version,
        )
    if len(prompt) > active_limits.max_prompt_chars:
        return _failure(
            code="prompt_over_limit",
            message=(
                f"chapter prompt ({len(prompt)} chars) exceeds max_prompt_chars "
                f"({active_limits.max_prompt_chars}); refusing to truncate "
                "chapter context (fail closed)"
            ),
            attempts=[],
            request=request,
            model_name=model_name,
            limits=active_limits,
            candidate_version=candidate_version,
        )

    fingerprints = fingerprints_for(
        request, model_name=model_name, limits=active_limits,
        candidate_version=candidate_version,
    )
    attempts: list[dict[str, Any]] = []
    candidate: dict[str, Any] | None = None

    for round_no in range(1 + active_limits.max_correction_rounds):
        kind = "initial" if round_no == 0 else "correction"
        started = time.monotonic()
        try:
            raw_response = model.complete(prompt)
        except Exception as exc:
            attempts.append(
                _attempt(
                    kind=kind,
                    prompt=prompt,
                    raw_response=None,
                    transport_error=f"model call failed: {exc}",
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
            )
            # Transport retry belongs to T06; this layer records and fails.
            return {
                "accepted": False,
                "artifact": None,
                "attempts": attempts,
                "error": {
                    "code": "model_transport_error",
                    "message": (
                        f"chapter extraction stopped on model transport failure "
                        f"({exc}); transport retry belongs to the provider layer, "
                        "not to the semantic correction round"
                    ),
                },
                "request_fingerprint": fingerprints["request_fingerprint"],
                "fingerprints": fingerprints,
                "correction_rounds_used": round_no,
                "transport_retries": TRANSPORT_RETRIES_HERE,
            }
        # Wall-clock cost of this semantic round's single model call, kept
        # on every attempt of the round for live usage/timing evidence.
        latency_ms = int((time.monotonic() - started) * 1000)
        if not isinstance(raw_response, str):
            attempts.append(
                _attempt(
                    kind=kind,
                    prompt=prompt,
                    raw_response=None,
                    transport_error=(
                        "model.complete must return response text, "
                        f"got {type(raw_response).__name__}"
                    ),
                    latency_ms=latency_ms,
                )
            )
            return {
                "accepted": False,
                "artifact": None,
                "attempts": attempts,
                "error": {
                    "code": "model_transport_error",
                    "message": "model.complete returned non-text output (fail closed)",
                },
                "request_fingerprint": fingerprints["request_fingerprint"],
                "fingerprints": fingerprints,
                "correction_rounds_used": round_no,
                "transport_retries": TRANSPORT_RETRIES_HERE,
            }
        if len(raw_response.encode("utf-8")) > active_limits.max_response_bytes:
            attempts.append(_attempt(kind=kind, prompt=prompt, raw_response=raw_response, latency_ms=latency_ms))
            return {
                "accepted": False,
                "artifact": None,
                "attempts": attempts,
                "error": {
                    "code": "response_over_limit_bytes",
                    "message": (
                        f"model response ({len(raw_response.encode('utf-8'))} bytes) "
                        f"exceeds max_response_bytes ({active_limits.max_response_bytes}); "
                        "refusing to truncate (fail closed)"
                    ),
                },
                "request_fingerprint": fingerprints["request_fingerprint"],
                "fingerprints": fingerprints,
                "correction_rounds_used": round_no,
                "transport_retries": TRANSPORT_RETRIES_HERE,
            }
        if len(raw_response) > active_limits.max_response_chars:
            attempts.append(_attempt(kind=kind, prompt=prompt, raw_response=raw_response, latency_ms=latency_ms))
            return {
                "accepted": False,
                "artifact": None,
                "attempts": attempts,
                "error": {
                    "code": "response_over_limit_chars",
                    "message": (
                        f"model response ({len(raw_response)} chars) exceeds "
                        f"max_response_chars ({active_limits.max_response_chars}); "
                        "refusing to truncate (fail closed)"
                    ),
                },
                "request_fingerprint": fingerprints["request_fingerprint"],
                "fingerprints": fingerprints,
                "correction_rounds_used": round_no,
                "transport_retries": TRANSPORT_RETRIES_HERE,
            }
        try:
            candidate = parse_candidate_response(raw_response)
            parse_error: str | None = None
        except ChapterModelError as exc:
            candidate = None
            parse_error = str(exc)
        if parse_error is not None:
            attempts.append(
                _attempt(
                    kind=kind, prompt=prompt, raw_response=raw_response,
                    parse_error=parse_error, latency_ms=latency_ms,
                )
            )
            if round_no >= active_limits.max_correction_rounds:
                break
            try:
                prompt = P.render_chapter_prompt(
                    request,
                    validation_errors=[f"response_parse: {parse_error}"],
                    previous_candidate={"note": "no parseable candidate was returned"},
                )
            except PersistenceError as exc:
                return {
                    "accepted": False,
                    "artifact": None,
                    "attempts": attempts,
                    "error": {
                        "code": "correction_prompt_over_limit",
                        "message": f"correction prompt cannot be rendered: {exc}",
                    },
                    "request_fingerprint": fingerprints["request_fingerprint"],
                    "fingerprints": fingerprints,
                    "correction_rounds_used": round_no,
                    "transport_retries": TRANSPORT_RETRIES_HERE,
                }
            if len(prompt) > active_limits.max_prompt_chars:
                attempts.append(
                    _attempt(
                        kind="correction-skipped",
                        prompt=None,
                        raw_response=None,
                        parse_error=(
                            "correction prompt exceeds max_prompt_chars; "
                            "refusing to truncate (fail closed)"
                        ),
                    )
                )
                return {
                    "accepted": False,
                    "artifact": None,
                    "attempts": attempts,
                    "error": {
                        "code": "correction_prompt_over_limit",
                        "message": "correction prompt exceeds max_prompt_chars (fail closed)",
                    },
                    "request_fingerprint": fingerprints["request_fingerprint"],
                    "fingerprints": fingerprints,
                    "correction_rounds_used": round_no,
                    "transport_retries": TRANSPORT_RETRIES_HERE,
                }
            continue
        report = _validate_candidate(
            request, candidate, candidate_version=candidate_version
        )
        correction_validation = None
        if round_no and candidate_version in (
            READING_CANDIDATE_VERSION, PERSON_STATE_CANDIDATE_VERSION,
        ):
            previous = attempts[0]
            correction_validation = _validate_correction(
                previous.get("candidate"), previous.get("validation"), candidate,
                candidate_version=candidate_version,
            )
        attempts.append(
            _attempt(
                kind=kind, prompt=prompt, raw_response=raw_response,
                validation=report, candidate=candidate, latency_ms=latency_ms,
                correction_validation=correction_validation,
            )
        )
        if report.get("passed") and (
            correction_validation is None or correction_validation["passed"]
        ):
            artifact = _accept_candidate(
                request,
                candidate,
                candidate_version=candidate_version,
                producing_run=_producing_run(
                    model_name=model_name,
                    request_fingerprint=fingerprints["request_fingerprint"],
                    candidate_version=candidate_version,
                ),
            )
            return {
                "accepted": True,
                "artifact": artifact,
                "attempts": attempts,
                "error": None,
                "request_fingerprint": fingerprints["request_fingerprint"],
                "fingerprints": fingerprints,
                "correction_rounds_used": round_no,
                "transport_retries": TRANSPORT_RETRIES_HERE,
            }
        if round_no >= active_limits.max_correction_rounds:
            break
        try:
            prompt = P.render_chapter_prompt(
                request,
                validation_errors=_flatten_report_errors(report),
                previous_candidate=candidate,
                preserve_translation=_preserve_translation(
                    candidate, report, candidate_version=candidate_version,
                ),
            )
        except PersistenceError as exc:
            return {
                "accepted": False,
                "artifact": None,
                "attempts": attempts,
                "error": {
                    "code": "correction_prompt_over_limit",
                    "message": f"correction prompt cannot be rendered: {exc}",
                },
                "request_fingerprint": fingerprints["request_fingerprint"],
                "fingerprints": fingerprints,
                "correction_rounds_used": round_no,
                "transport_retries": TRANSPORT_RETRIES_HERE,
            }
        if len(prompt) > active_limits.max_prompt_chars:
            attempts.append(
                _attempt(
                    kind="correction-skipped",
                    prompt=None,
                    raw_response=None,
                    parse_error=(
                        "correction prompt exceeds max_prompt_chars; "
                        "refusing to truncate (fail closed)"
                    ),
                )
            )
            return {
                "accepted": False,
                "artifact": None,
                "attempts": attempts,
                "error": {
                    "code": "correction_prompt_over_limit",
                    "message": "correction prompt exceeds max_prompt_chars (fail closed)",
                },
                "request_fingerprint": fingerprints["request_fingerprint"],
                "fingerprints": fingerprints,
                "correction_rounds_used": round_no,
                "transport_retries": TRANSPORT_RETRIES_HERE,
            }

    last = attempts[-1] if attempts else None
    detail = "no model attempt was recorded"
    categories: dict[str, int] = {}
    if last is not None:
        if last.get("parse_error"):
            detail = last["parse_error"]
        elif last.get("validation") is not None:
            detail = "; ".join(_flatten_report_errors(last["validation"]))
            categories = _error_categories(last["validation"])
            correction_errors = (last.get("correction_validation") or {}).get("errors", [])
            if correction_errors:
                categories["translation_preservation"] = len(correction_errors)
                detail = "; ".join(filter(None, [
                    detail, *(f"translation_preservation: {e}" for e in correction_errors),
                ]))
    correction_rounds_used = sum(1 for a in attempts if a.get("kind") == "correction")
    return {
        "accepted": False,
        "artifact": None,
        "attempts": attempts,
        "error": {
            "code": "validation_failed" if last and last.get("validation") is not None else "response_parse",
            "message": (
                f"chapter extraction failed closed after {len(attempts)} attempt(s): {detail}"
            ),
            # Consumer-side triage: which contract categories failed (for
            # example reading_coverage / reading_spans / reading_time), so a
            # missing annotation or overlapping span is checkable without
            # parsing the free-form message.
            "categories": categories,
        },
        "request_fingerprint": fingerprints["request_fingerprint"],
        "fingerprints": fingerprints,
        "correction_rounds_used": correction_rounds_used,
        "transport_retries": TRANSPORT_RETRIES_HERE,
    }


def _history_attempt_bindings(
    attempt: dict[str, Any], *, prompt_version: str,
) -> list[str]:
    """Verify the retained bytes/header, not only editable run-level labels."""
    errors: list[str] = []
    prompt = attempt.get("prompt")
    if isinstance(prompt, str):
        if (
            attempt.get("prompt_sha256") != sha256_text(prompt)
            or attempt.get("prompt_chars") != len(prompt)
        ):
            errors.append("prompt hash/size mismatch")
        try:
            prefix, header_text = prompt.split("\nCHAPTER REQUEST\n", 1)
            header, _ = json.JSONDecoder().raw_decode(
                header_text.lstrip()
            )
            # Legacy repairs precede the request; new repairs follow the
            # full chapter. Exclude the source body from marker inspection.
            suffix = prompt.rsplit("\n---END CHAPTER---\n", 1)[-1]
            correction_prompt = "\nCORRECTION RE-ASK\n" in prefix + suffix
            if correction_prompt != (attempt.get("kind") == "correction"):
                errors.append("prompt repair scope disagrees with attempt kind")
        except ValueError:
            header = None
        if not isinstance(header, dict) or header.get("prompt_version") != prompt_version:
            errors.append("prompt header/version mismatch")
    elif attempt.get("kind") != "correction-skipped":
        errors.append("missing prompt for a model attempt")
    raw = attempt.get("raw_response")
    if isinstance(raw, str) and (
        attempt.get("raw_response_sha256") != sha256_text(raw)
        or attempt.get("raw_response_chars") != len(raw)
        or attempt.get("raw_response_bytes") != len(raw.encode("utf-8"))
    ):
        errors.append("raw response hash/size mismatch")
    return errors


def verify_history(result: dict[str, Any], *, request: dict[str, Any]) -> list[str]:
    """Replay validation over a stored result; return mismatches (empty = OK).

    For every attempt carrying both a raw response and a stored
    validation report, re-parse and re-validate and compare the pass/fail
    outcome plus the flattened error set. New 0.2/0.3 runs also replay the
    correction policy from the raw initial/corrected candidates. The
    original v1 extraction histories retain their pre-policy interpretation.
    A mismatch means the history is not replayable and must fail closed.
    """
    mismatches: list[str] = []
    attempts = result.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        return ["result carries no attempt history"]
    try:
        candidate_version = request_candidate_version(request)
    except PersistenceError as exc:
        return [f"stored request declares no usable candidate version: {exc}"]
    check_correction = False
    check_bindings = candidate_version in (
        READING_CANDIDATE_VERSION, PERSON_STATE_CANDIDATE_VERSION,
    )
    if check_bindings:
        fingerprints = result.get("fingerprints")
        if not isinstance(fingerprints, dict):
            return ["stored run carries no usable fingerprints"]
        extraction_version = fingerprints.get("extraction_version")
        policy_version = fingerprints.get("correction_policy_version")
        prompt_version = fingerprints.get("prompt_version")
        if (
            not isinstance(extraction_version, str)
            or not isinstance(prompt_version, str)
            or (policy_version is not None and not isinstance(policy_version, str))
            or prompt_version not in _HISTORY_PROMPT_VERSIONS.get(
                (candidate_version, extraction_version, policy_version), set(),
            )
        ):
            return [f"unsupported extraction/correction policy: {extraction_version!r}/{policy_version!r}"]
        check_correction = policy_version == CORRECTION_POLICY_VERSION
        kinds = [a.get("kind") if isinstance(a, dict) else None for a in attempts]
        if kinds not in (["initial"], ["initial", "correction"], ["initial", "correction-skipped"]):
            mismatches.append("history must contain an initial attempt and at most one correction")
        if result.get("correction_rounds_used") != kinds.count("correction"):
            mismatches.append("correction_rounds_used disagrees with attempt history")
    previous_candidate = previous_report = None
    passing_attempts: list[bool] = []
    for position, attempt in enumerate(attempts, 1):
        if not isinstance(attempt, dict):
            mismatches.append(f"attempt {position} is not a JSON object")
            continue
        if check_bindings:
            mismatches.extend(
                f"attempt {position} {message}"
                for message in _history_attempt_bindings(attempt, prompt_version=prompt_version)
            )
        if attempt.get("correction_validation") is not None and (
            not check_correction or attempt.get("kind") != "correction"
        ):
            mismatches.append(f"attempt {position} has an unexpected correction policy")
        if check_correction and (
            (position == 1 and attempt.get("kind") != "initial")
            or (position > 1 and attempt.get("kind") not in ("correction", "correction-skipped"))
        ):
            mismatches.append(f"attempt {position} has an invalid correction sequence")
        stored = attempt.get("validation")
        raw = attempt.get("raw_response")
        # Only an actual parse failure can lead to a correction without an
        # initial validation report. Missing first-draft evidence must not
        # silently disable preservation for the second response.
        if check_bindings and position == 1 and "correction" in kinds:
            if not isinstance(raw, str):
                mismatches.append("initial raw response is missing before correction")
            elif stored is None:
                try:
                    parse_candidate_response(raw)
                except ChapterModelError as exc:
                    if attempt.get("parse_error") != str(exc):
                        mismatches.append("initial parse error disagrees with its raw response")
                else:
                    mismatches.append("initial validation is missing before correction")
        if check_bindings and stored is not None and raw is None:
            mismatches.append(f"attempt {position} validation has no raw response")
        if stored is None or raw is None:
            continue  # Transport/size/policy failures have nothing to replay.
        if (
            not isinstance(stored, dict) or not isinstance(stored.get("errors"), dict)
            or any(
                not isinstance(messages, list) or any(not isinstance(e, str) for e in messages)
                for messages in stored["errors"].values()
            )
        ):
            mismatches.append(f"attempt {position} carries a malformed validation report")
            continue
        try:
            candidate = parse_candidate_response(raw)
        except ChapterModelError as exc:
            mismatches.append(f"attempt {position} no longer parses: {exc}")
            continue
        if check_bindings and candidate != attempt.get("candidate"):
            mismatches.append(f"attempt {position} cached candidate disagrees with raw response")
        try:
            report = _validate_candidate(
                request, candidate, candidate_version=candidate_version
            )
        except Exception as exc:  # fail closed on any replay breakage
            mismatches.append(f"attempt {position} no longer validates: {exc}")
            continue
        passed = bool(report.get("passed"))
        if check_correction and position > 1:
            correction = _validate_correction(
                previous_candidate, previous_report, candidate,
                candidate_version=candidate_version,
            )
            if correction != attempt.get("correction_validation"):
                mismatches.append(f"attempt {position} replay disagrees on correction policy")
            passed = passed and correction["passed"]
        if position == 1:
            previous_candidate, previous_report = candidate, report
            if check_bindings and passed and "correction" in kinds:
                mismatches.append("correction follows an already passing initial candidate")
        passing_attempts.append(passed)
        if bool(report.get("passed")) != bool(stored.get("passed")):
            mismatches.append(
                f"attempt {position} replay disagrees on outcome: stored "
                f"{stored.get('passed')!r} vs replay {report.get('passed')!r}"
            )
            continue
        if set(_flatten_report_errors(report)) != set(_flatten_report_errors(stored)):
            mismatches.append(f"attempt {position} replay disagrees on error set")
    if result.get("accepted") and not any(passing_attempts):
        mismatches.append("result claims accepted output with no passing attempt")
    if not result.get("accepted") and any(passing_attempts):
        mismatches.append("result rejects output despite a passing attempt")
    return mismatches
