"""Deployment model provider boundary for Chronicle ingestion workers.

C1-T13 needs the already-tested C1 extraction/presentation provider protocols
to be reachable from the real Docker worker. This module intentionally keeps
that deployment I/O vendor-neutral: it speaks the small HTTP subset used by a
Responses-style endpoint and returns only produced text.

Extraction and Reader Presentation each supply their own strict structured-
output constraint derived from their canonical contract. These constrain
generation only; the existing schema/grounding/reference/time/uncertainty
validators remain the acceptance authority.

Development may instead opt in to ``CHRONICLE_MODEL_FIXTURE_PACK``. That mode
uses the same model boundary and normal Chronicle validators/persistence path;
it is explicit and mutually exclusive with an external endpoint so production
can never silently fall back to fixture history.

Historical authority does not move here. Providers only supply raw model text
to the existing extraction / Reader Presentation validators; those layers
remain responsible for evidence grounding, schema validation, conservative
resolution, and fail-closed publication.
"""

from __future__ import annotations

import json
import os
import time
import asyncio
from dataclasses import dataclass
from typing import Any, Mapping
from urllib import error, parse, request

from common import PersistenceError

try:
    from extraction_model_schema import (
        chapter_candidate_text_format,
        chapter_candidate_text_format_for,
        extraction_text_format,
    )
    from presentation_model_schema import presentation_text_format
except ImportError:  # pragma: no cover - package import path
    from .extraction_model_schema import (
        chapter_candidate_text_format,
        chapter_candidate_text_format_for,
        extraction_text_format,
    )
    from .presentation_model_schema import presentation_text_format

#: Frozen joint-provider generation (new live chapter work uses staged 0.4
#: through chapter_models, never this whole-candidate provider).
PRODUCTION_CHAPTER_CANDIDATE_VERSION = "0.3"

DEFAULT_MODEL_TIMEOUT_SECONDS = 600.0
# Legacy C1 extraction/presentation transport bound. Kept at 2 MiB so the
# existing providers constructed by ``models_from_env()`` keep their exact
# historical accepted response size; T06 must not change their behavior.
DEFAULT_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
# Chapter-production §3 engineering envelope (T01 ChapterLimits): the chapter
# provider accepts up to 4 MiB HTTP response bytes. This is a transport
# bound, not a model capability claim; larger payloads fail closed as
# oversize responses. Applied only through ``build_chapter_model()``.
DEFAULT_CHAPTER_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
# Chapter-production §3 provider output budget (T01 ChapterLimits
# max_output_tokens). Sent as ``max_output_tokens`` on chapter requests so
# the model receives an explicit output token limit alongside the strict
# structured-output schema.
DEFAULT_CHAPTER_MAX_OUTPUT_TOKENS = 65536
DEFAULT_MODEL_MAX_ATTEMPTS = 3
DEFAULT_MODEL_RETRY_BACKOFF_SECONDS = 1.0
MODEL_HTTP_USER_AGENT = "Loom-Chronicle/0.1"
TRANSIENT_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504, 520, 522, 523, 524})


class ModelProviderError(RuntimeError):
    """Raised when the configured model endpoint cannot produce valid text."""

    def __init__(self, message: str, *, receipt: dict | None = None, raw_text: str = ""):
        super().__init__(message)
        self.receipt = receipt
        self.raw_text = raw_text


def _nonempty_env(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _validate_endpoint(endpoint: str) -> str:
    value = endpoint.strip()
    parsed = parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PersistenceError(
            "CHRONICLE_MODEL_ENDPOINT must be an absolute http(s) URL"
        )
    if parsed.username is not None or parsed.password is not None:
        raise PersistenceError(
            "CHRONICLE_MODEL_ENDPOINT must not embed credentials; use "
            "CHRONICLE_MODEL_API_KEY instead"
        )
    return value


def timeout_from_env(env: Mapping[str, str] | None = None) -> float:
    """Return the per-attempt HTTP timeout for live model providers.

    Honors ``CHRONICLE_MODEL_TIMEOUT_SECONDS`` from the given mapping
    (or the process environment when omitted) with the same
    positive-number validation as the C1 extraction/presentation path,
    so the joint chapter pipeline observes the deployed timeout instead
    of silently falling back to the code default.
    """
    if env is None:
        raw_value = _nonempty_env("CHRONICLE_MODEL_TIMEOUT_SECONDS")
    else:
        raw = env.get("CHRONICLE_MODEL_TIMEOUT_SECONDS")
        raw_value = raw.strip() if isinstance(raw, str) else None
        if not raw_value:
            raw_value = None
    if raw_value is None:
        return DEFAULT_MODEL_TIMEOUT_SECONDS
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise PersistenceError(
            "CHRONICLE_MODEL_TIMEOUT_SECONDS must be a positive number"
        ) from exc
    if value <= 0:
        raise PersistenceError(
            "CHRONICLE_MODEL_TIMEOUT_SECONDS must be a positive number"
        )
    return value


def _timeout_from_env() -> float:
    return timeout_from_env()


def _response_text(payload: Any) -> str:
    """Extract generated text from a Responses-style JSON object.

    Completion requires an explicit completed status when the endpoint
    reports one: ``incomplete`` (e.g. ``max_output_tokens``/``length``),
    ``failed``/``cancelled``, a non-empty ``incomplete_details`` reason, or
    any refusal entry means the turn did not complete, even when a partial
    ``output_text`` fragment is present. Partial content must never be
    treated as a finished chapter candidate; content correction belongs to
    the extraction stage (C2-R1-T05), not to this HTTP adapter, so this
    function raises instead of repairing or re-writing model output.
    """
    if not isinstance(payload, dict):
        raise ModelProviderError("model response must be a JSON object")

    status = payload.get("status")
    if isinstance(status, str) and status not in ("completed", "succeeded"):
        raise ModelProviderError(
            f"model response did not complete (status {status})"
        )
    incomplete = payload.get("incomplete_details")
    if isinstance(incomplete, dict):
        reason = incomplete.get("reason")
        if isinstance(reason, str) and reason.strip():
            raise ModelProviderError(
                f"model response did not complete (reason {reason.strip()})"
            )
        if incomplete:
            raise ModelProviderError("model response did not complete (incomplete)")
    # Response-level refusal fails the turn. Nested per-block refusal
    # entries inside ``output[].content`` keep the historical lenient
    # behavior (ignored while other output_text blocks are used); only a
    # top-level refusal, an explicit non-completed status, or a non-empty
    # incomplete_details reason marks the whole turn incomplete.
    refusal = payload.get("refusal")
    if isinstance(refusal, str) and refusal.strip():
        raise ModelProviderError("model response was refused")

    parts: list[str] = []
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "output_text":
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                if not isinstance(content_item, dict):
                    continue
                if content_item.get("type") != "output_text":
                    continue
                text = content_item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)

    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct

    joined = "".join(parts)
    if joined.strip():
        return joined
    raise ModelProviderError("model response contains no output text")


@dataclass(frozen=True)
class ResponsesHTTPModel:
    """Small synchronous provider implementing Chronicle's ``complete`` hook.

    ``timeout_seconds`` is the timeout for each HTTP attempt, not a shared
    budget across all retries. This distinction is important for long-running
    model requests: a transient connection failure that consumes one attempt's
    timeout must not silently make ``max_attempts > 1`` ineffective.
    """

    name: str
    endpoint: str
    api_key: str | None = None
    timeout_seconds: float = DEFAULT_MODEL_TIMEOUT_SECONDS
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    max_attempts: int = DEFAULT_MODEL_MAX_ATTEMPTS
    retry_backoff_seconds: float = DEFAULT_MODEL_RETRY_BACKOFF_SECONDS
    text_format: dict[str, Any] | None = None
    # Chapter output budget (chapter-production §3 / T01 ChapterLimits).
    # ``None`` omits the field so legacy chunk/presentation providers keep
    # their exact historical request shape; chapter providers set it
    # (default 65536) so the request carries an explicit output token limit.
    max_output_tokens: int | None = None
    # Worker-local contract metadata; never sent as a provider payload field.
    # The chapter factory binds this to the same version as text_format.
    candidate_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise PersistenceError("model name must be a non-empty string")
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "endpoint", _validate_endpoint(self.endpoint))
        if self.timeout_seconds <= 0:
            raise PersistenceError("model timeout must be positive")
        if self.max_response_bytes < 1:
            raise PersistenceError("model max_response_bytes must be positive")
        if (
            not isinstance(self.max_attempts, int)
            or isinstance(self.max_attempts, bool)
            or self.max_attempts < 1
        ):
            raise PersistenceError("model max_attempts must be a positive integer")
        if self.retry_backoff_seconds < 0:
            raise PersistenceError("model retry_backoff_seconds must be non-negative")
        if self.text_format is not None and not isinstance(self.text_format, dict):
            raise PersistenceError("model text_format must be a JSON object")
        if self.max_output_tokens is not None and (
            not isinstance(self.max_output_tokens, int)
            or isinstance(self.max_output_tokens, bool)
            or self.max_output_tokens < 1
        ):
            raise PersistenceError("model max_output_tokens must be a positive integer")

    def complete(self, prompt: str) -> str:
        if not isinstance(prompt, str) or not prompt:
            raise ModelProviderError("model prompt must be a non-empty string")

        payload: dict[str, Any] = {"model": self.name, "input": prompt}
        if self.text_format is not None:
            payload["text"] = {"format": self.text_format}
        if self.max_output_tokens is not None:
            payload["max_output_tokens"] = self.max_output_tokens
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": MODEL_HTTP_USER_AGENT,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        attempts_made = 0
        last_transient = "transport failure"

        for attempt in range(1, self.max_attempts + 1):
            attempts_made += 1
            req = request.Request(
                self.endpoint,
                data=body,
                headers=headers,
                method="POST",
            )

            try:
                with request.urlopen(req, timeout=self.timeout_seconds) as response:
                    content_length = response.headers.get("Content-Length")
                    if content_length is not None:
                        try:
                            declared = int(content_length)
                        except ValueError:
                            declared = 0
                        if declared > self.max_response_bytes:
                            raise ModelProviderError(
                                "model response exceeds configured size limit"
                            )
                    raw = response.read(self.max_response_bytes + 1)
            except error.HTTPError as exc:
                # Never echo a provider body: gateways may include request
                # details, credentials, source text, or model output.
                if exc.code not in TRANSIENT_HTTP_STATUSES:
                    raise ModelProviderError(
                        f"model endpoint returned HTTP {exc.code}"
                    ) from exc
                last_transient = f"HTTP {exc.code}"
            except (error.URLError, TimeoutError, OSError):
                last_transient = "transport failure"
            else:
                if len(raw) > self.max_response_bytes:
                    raise ModelProviderError(
                        "model response exceeds configured size limit"
                    )
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ModelProviderError(
                        "model endpoint returned invalid JSON"
                    ) from exc
                return _response_text(payload)

            if attempt >= self.max_attempts:
                break

            backoff = self.retry_backoff_seconds * (2 ** (attempt - 1))
            if backoff > 0:
                time.sleep(backoff)

        raise ModelProviderError(
            "model endpoint transient failure after "
            f"{attempts_made} attempt(s): {last_transient}"
        )

    def complete_with_receipt(self, prompt: str, *, total_timeout_seconds: float,
                              on_progress=None, cancelled=None) -> tuple[str, dict]:
        """One observable HTTP attempt with an actual wall-clock deadline.

        The staged scheduler owns retries and persists each attempt. Use an
        interruptible async transport here so a peer sending keep-alive bytes
        cannot reset the total budget indefinitely. The legacy complete hook
        retains its frozen retry behavior; both paths use the same Responses
        payload and text/status validation. Raw reasoning/envelopes are never
        returned to the product audit log.
        """
        if not isinstance(prompt, str) or not prompt or total_timeout_seconds <= 0:
            raise ModelProviderError("model prompt and total deadline are required")
        try:
            import httpx
        except ImportError as exc:
            raise PersistenceError("install apps/chronicle/worker/requirements.txt for staged model transport") from exc
        started = time.monotonic()
        receipt: dict[str, Any] = {
            "requested_model": self.name, "model": None, "status": "started",
            "usage": None, "http_attempts": 1, "response_bytes": 0,
            "elapsed_seconds": 0.0, "incomplete_reason": None,
        }
        payload: dict[str, Any] = {"model": self.name, "input": prompt}
        if self.text_format is not None:
            payload["text"] = {"format": self.text_format}
        if self.max_output_tokens is not None:
            payload["max_output_tokens"] = self.max_output_tokens
        headers = {"Accept": "application/json", "User-Agent": MODEL_HTTP_USER_AGENT}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async def perform():
            async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False) as client:
                async with client.stream("POST", self.endpoint, json=payload, headers=headers) as response:
                    receipt["http_status"] = response.status_code
                    if response.status_code >= 300:
                        raise ModelProviderError(f"model endpoint returned HTTP {response.status_code}")
                    chunks: list[bytes] = []
                    count = 0
                    async for chunk in response.aiter_bytes():
                        count += len(chunk)
                        receipt["response_bytes"] = count
                        if count > self.max_response_bytes:
                            raise ModelProviderError("model response exceeds configured size limit")
                        chunks.append(chunk)
                        if on_progress is not None:
                            on_progress({"response_bytes": count,
                                         "elapsed_seconds": time.monotonic() - started})
                    return b"".join(chunks)

        async def perform_cancellable():
            # Watch independently of response bytes: a peer may send neither
            # headers nor content after the job has been cancelled or lost.
            async def watch_cancellation():
                while cancelled is None or not cancelled():
                    await asyncio.sleep(0.1)
                receipt["status"] = "cancelled"
                raise ModelProviderError("model attempt cancelled")

            if cancelled is not None and cancelled():
                receipt["status"] = "cancelled"
                raise ModelProviderError("model attempt cancelled before dispatch")
            request_task = asyncio.create_task(perform())
            tasks = [request_task]
            if cancelled is not None:
                tasks.append(asyncio.create_task(watch_cancellation()))
            try:
                completed, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                if len(tasks) > 1 and tasks[1] in completed:
                    return tasks[1].result()
                return request_task.result()
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        async def bounded_attempt():
            # wait_for also supports the repository's Python 3.9 test runtime.
            return await asyncio.wait_for(perform_cancellable(), timeout=total_timeout_seconds)

        raw_text = ""
        try:
            raw = asyncio.run(bounded_attempt())
            try:
                response = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise ModelProviderError("model endpoint returned invalid JSON") from exc
            if not isinstance(response, dict):
                raise ModelProviderError("model response must be a JSON object")
            receipt["status"] = response.get("status")
            receipt["model"] = response.get("model") if isinstance(response.get("model"), str) else None
            usage = response.get("usage")
            if isinstance(usage, dict):
                safe_usage = {}
                for key in ("input_tokens", "output_tokens", "total_tokens"):
                    value = usage.get(key)
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                        safe_usage[key] = value
                details = usage.get("output_tokens_details")
                if (isinstance(details, dict) and isinstance(details.get("reasoning_tokens"), int)
                        and not isinstance(details["reasoning_tokens"], bool) and details["reasoning_tokens"] >= 0):
                    safe_usage["reasoning_tokens"] = details["reasoning_tokens"]
                receipt["usage"] = safe_usage or None
            incomplete = response.get("incomplete_details")
            if isinstance(incomplete, dict):
                reason = incomplete.get("reason")
                if reason in ("max_output_tokens", "content_filter"):
                    receipt["incomplete_reason"] = reason
                elif reason:
                    receipt["incomplete_reason"] = "other"
            # Save any visible incomplete output for diagnosis, but never
            # treat it as a completed candidate. Reasoning is not extracted.
            try:
                raw_text = _response_text({**response, "status": "completed", "incomplete_details": None, "refusal": None})
            except ModelProviderError:
                pass
            if response.get("status") not in ("completed", "succeeded"):
                raise ModelProviderError("model response did not explicitly complete")
            for item in response.get("output") or []:
                if isinstance(item, dict) and any(
                    isinstance(part, dict) and part.get("type") == "refusal"
                    for part in item.get("content") or []
                ):
                    raise ModelProviderError("model response was refused")
            text = _response_text(response)
            receipt["status"] = "completed"
            return text, receipt
        except (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException) as exc:
            receipt["status"] = "timeout"
            raise ModelProviderError("model attempt exceeded its time budget", receipt=receipt, raw_text=raw_text) from exc
        except httpx.HTTPError as exc:
            receipt["status"] = "transport_error"
            raise ModelProviderError("model endpoint transport failure", receipt=receipt, raw_text=raw_text) from exc
        except ModelProviderError as exc:
            if receipt["status"] in ("started", "completed", None):
                receipt["status"] = "failed"
            raise ModelProviderError(str(exc), receipt=receipt, raw_text=raw_text) from exc
        finally:
            receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)


def _fixture_models_from_env() -> tuple[Any, Any] | None:
    """Build the explicit development fixture provider when requested.

    Fixture mode and external-provider mode are mutually exclusive. This makes
    fixture use visible in configuration and prevents a missing/invalid live
    provider from ever degrading into deterministic development output.
    """
    fixture_pack = _nonempty_env("CHRONICLE_MODEL_FIXTURE_PACK")
    if fixture_pack is None:
        return None
    conflicting = [
        name
        for name in (
            "CHRONICLE_MODEL_ENDPOINT",
            "CHRONICLE_MODEL_API_KEY",
            "CHRONICLE_EXTRACTION_MODEL",
            "CHRONICLE_PRESENTATION_MODEL",
        )
        if _nonempty_env(name) is not None
    ]
    if conflicting:
        raise PersistenceError(
            "CHRONICLE_MODEL_FIXTURE_PACK cannot be combined with external "
            f"model configuration ({', '.join(conflicting)})"
        )
    # Imported lazily so production HTTP-only deployments do not gain any
    # fixture behavior unless the explicit environment variable is present.
    import fixture_model

    return fixture_model.models_from_fixture_pack(fixture_pack)


def models_from_env() -> tuple[Any | None, Any | None]:
    """Build independently configured extraction/presentation providers.

    ``CHRONICLE_MODEL_FIXTURE_PACK`` is an explicit development-only mode and
    returns both fixture providers. Otherwise, no model names preserves the
    pre-C1-T13 worker behavior exactly. Once either live model is requested, an
    explicit endpoint is required so a deployment can choose OpenAI, Luna
    through a compatible gateway, or a local Responses-compatible service
    without Chronicle guessing a vendor.

    Each live model receives the strict structured-output constraint for its
    own contract and is validated independently after generation.
    """
    fixture_models = _fixture_models_from_env()
    if fixture_models is not None:
        return fixture_models

    extraction_name = _nonempty_env("CHRONICLE_EXTRACTION_MODEL")
    presentation_name = _nonempty_env("CHRONICLE_PRESENTATION_MODEL")
    if extraction_name is None and presentation_name is None:
        return None, None

    endpoint = _nonempty_env("CHRONICLE_MODEL_ENDPOINT")
    if endpoint is None:
        raise PersistenceError(
            "CHRONICLE_MODEL_ENDPOINT is required when a Chronicle model is configured"
        )
    endpoint = _validate_endpoint(endpoint)
    api_key = _nonempty_env("CHRONICLE_MODEL_API_KEY")
    timeout = _timeout_from_env()

    def build(
        name: str | None,
        *,
        text_format: dict[str, Any] | None = None,
    ) -> ResponsesHTTPModel | None:
        if name is None:
            return None
        return ResponsesHTTPModel(
            name=name,
            endpoint=endpoint,
            api_key=api_key,
            timeout_seconds=timeout,
            text_format=text_format,
        )

    return (
        build(extraction_name, text_format=extraction_text_format()),
        build(presentation_name, text_format=presentation_text_format()),
    )


def build_chapter_model(
    name: str,
    endpoint: str,
    *,
    api_key: str | None = None,
    timeout_seconds: float = DEFAULT_MODEL_TIMEOUT_SECONDS,
    max_response_bytes: int = DEFAULT_CHAPTER_MAX_RESPONSE_BYTES,
    max_output_tokens: int = DEFAULT_CHAPTER_MAX_OUTPUT_TOKENS,
    max_attempts: int = DEFAULT_MODEL_MAX_ATTEMPTS,
    retry_backoff_seconds: float = DEFAULT_MODEL_RETRY_BACKOFF_SECONDS,
    candidate_version: str | None = None,
) -> ResponsesHTTPModel:
    """Build the chapter-production provider for one joint generation call.

    The request carries the chapter-candidate strict format (only
    model-generatable fields) plus the chapter-production §3 output token
    budget and 4 MiB response byte cap. ``candidate_version`` selects the
    strict contract; this frozen joint factory defaults to 0.3 person states
    on top of the reading annotations. New staged work uses ChapterModels.
    Acceptance still runs
    the matching T01/reading/person-state validator on the returned text;
    this factory only constrains generation and transport. Legacy
    extraction/presentation providers keep their own 2 MiB default and are
    unaffected.

    Worker selection and environment wiring belong to C2-R1-T13/T16; this
    helper exists so that wiring can construct the provider without
    duplicating the chapter envelope.
    """
    version = candidate_version or PRODUCTION_CHAPTER_CANDIDATE_VERSION
    return ResponsesHTTPModel(
        name=name,
        endpoint=endpoint,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        max_response_bytes=max_response_bytes,
        max_attempts=max_attempts,
        retry_backoff_seconds=retry_backoff_seconds,
        text_format=chapter_candidate_text_format_for(version),
        max_output_tokens=max_output_tokens,
        candidate_version=version,
    )
