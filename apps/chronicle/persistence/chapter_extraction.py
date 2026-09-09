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
      "attempts": [...],                # one entry per model call, verbatim
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
from typing import Any, Protocol

import chapter_contract as C
import chapter_prompt as P
from common import PersistenceError

#: Version of this whole-chapter extraction pipeline step.
EXTRACTION_VERSION = "c2r1-extraction-v1"

#: Prompt template version bound into every attempt and producing run.
PROMPT_VERSION = P.PROMPT_VERSION

#: Model-generatable candidate marker accepted here (T01 contract).
CANDIDATE_SCHEMA = P.CANDIDATE_SCHEMA
CANDIDATE_VERSION = P.CANDIDATE_VERSION

#: Transport-retry ownership marker: this layer never retries transport.
TRANSPORT_RETRIES_HERE = 0


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
) -> dict[str, Any]:
    """Bind limits/model/schema/source/plan versions for one execution."""
    return {
        "request_fingerprint": C.request_fingerprint(request),
        "limits": limits.to_dict(),
        "model": model_name,
        "prompt_version": PROMPT_VERSION,
        "extraction_version": EXTRACTION_VERSION,
        "candidate_schema": f"{CANDIDATE_SCHEMA}/{CANDIDATE_VERSION}",
        "source_sha256": request.get("source_sha256"),
        "normalized_sha256": request.get("normalized_sha256"),
        "plan_version": request.get("plan_version"),
        "chapter_id": request.get("chapter_id"),
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
) -> dict[str, Any]:
    return {
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
        "parse_error": parse_error,
        "transport_error": transport_error,
        "validation": copy.deepcopy(validation),
        "candidate": copy.deepcopy(candidate),
    }


def _failure(
    *,
    code: str,
    message: str,
    attempts: list[dict[str, Any]],
    request: dict[str, Any],
    model_name: str,
    limits: C.ChapterLimits,
    correction_rounds_used: int = 0,
) -> dict[str, Any]:
    fingerprints = None
    try:
        fingerprints = fingerprints_for(request, model_name=model_name, limits=limits)
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


def _producing_run(*, model_name: str, request_fingerprint: str) -> dict[str, Any]:
    digest = sha256_text(f"{request_fingerprint}|{model_name}|{PROMPT_VERSION}")[:16]
    return {
        "run_id": f"chapter-extract-{digest}",
        "model": model_name,
        "prompt_schema_version": PROMPT_VERSION,
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
        active_limits = _limits_for(request, limits)
    except PersistenceError as exc:
        return _failure(
            code="invalid_request",
            message=f"chapter request limits are invalid: {exc}",
            attempts=[],
            request=request,
            model_name=model_name,
            limits=C.ChapterLimits(),
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
        )

    fingerprints = fingerprints_for(request, model_name=model_name, limits=active_limits)
    attempts: list[dict[str, Any]] = []
    candidate: dict[str, Any] | None = None

    for round_no in range(1 + active_limits.max_correction_rounds):
        kind = "initial" if round_no == 0 else "correction"
        try:
            raw_response = model.complete(prompt)
        except Exception as exc:
            attempts.append(
                _attempt(
                    kind=kind,
                    prompt=prompt,
                    raw_response=None,
                    transport_error=f"model call failed: {exc}",
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
            attempts.append(_attempt(kind=kind, prompt=prompt, raw_response=raw_response))
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
            attempts.append(_attempt(kind=kind, prompt=prompt, raw_response=raw_response))
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
                    parse_error=parse_error,
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
        report = C.validate_chapter_candidate(request, candidate)
        attempts.append(
            _attempt(
                kind=kind, prompt=prompt, raw_response=raw_response,
                validation=report, candidate=candidate,
            )
        )
        if report.get("passed"):
            artifact = C.accept_chapter_candidate(
                request,
                candidate,
                producing_run=_producing_run(
                    model_name=model_name,
                    request_fingerprint=fingerprints["request_fingerprint"],
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
                validation_errors=flatten_validation_errors(report),
                previous_candidate=candidate,
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
    if last is not None:
        if last.get("parse_error"):
            detail = last["parse_error"]
        elif last.get("validation") is not None:
            detail = "; ".join(flatten_validation_errors(last["validation"]))
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
        },
        "request_fingerprint": fingerprints["request_fingerprint"],
        "fingerprints": fingerprints,
        "correction_rounds_used": correction_rounds_used,
        "transport_retries": TRANSPORT_RETRIES_HERE,
    }


def verify_history(result: dict[str, Any], *, request: dict[str, Any]) -> list[str]:
    """Replay validation over a stored result; return mismatches (empty = OK).

    For every attempt carrying both a raw response and a stored
    validation report, re-parse and re-validate and compare the pass/fail
    outcome plus the flattened error set. A mismatch means the history is
    not replayable and must fail closed downstream.
    """
    mismatches: list[str] = []
    attempts = result.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        return ["result carries no attempt history"]
    for position, attempt in enumerate(attempts, 1):
        if not isinstance(attempt, dict):
            mismatches.append(f"attempt {position} is not a JSON object")
            continue
        stored = attempt.get("validation")
        raw = attempt.get("raw_response")
        if stored is None or raw is None:
            continue  # Transport/size/policy failures have nothing to replay.
        try:
            candidate = parse_candidate_response(raw)
        except ChapterModelError as exc:
            mismatches.append(f"attempt {position} no longer parses: {exc}")
            continue
        try:
            report = C.validate_chapter_candidate(request, candidate)
        except Exception as exc:  # fail closed on any replay breakage
            mismatches.append(f"attempt {position} no longer validates: {exc}")
            continue
        if bool(report.get("passed")) != bool(stored.get("passed")):
            mismatches.append(
                f"attempt {position} replay disagrees on outcome: stored "
                f"{stored.get('passed')!r} vs replay {report.get('passed')!r}"
            )
            continue
        if set(flatten_validation_errors(report)) != set(flatten_validation_errors(stored)):
            mismatches.append(f"attempt {position} replay disagrees on error set")
    if result.get("accepted") and not any(
        isinstance(a, dict)
        and a.get("validation") is not None
        and a["validation"].get("passed")
        for a in attempts
    ):
        mismatches.append("result claims accepted output with no passing attempt")
    if not result.get("accepted") and any(
        isinstance(a, dict)
        and a.get("validation") is not None
        and a["validation"].get("passed")
        for a in attempts
    ):
        mismatches.append("result rejects output despite a passing attempt")
    return mismatches
