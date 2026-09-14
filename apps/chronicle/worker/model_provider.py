"""Vendor-neutral Responses transport for current Chronicle model steps.

This module validates transport configuration, performs bounded HTTP requests,
and returns model text plus a sanitized receipt. The staged chapter runner and
narrative runner own step schemas, source grounding, retries, and publication
decisions; no legacy extraction or presentation provider is selected here.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib import error, parse, request

from common import PersistenceError

DEFAULT_MODEL_TIMEOUT_SECONDS = 600.0
DEFAULT_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
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
    """Return the one global per-attempt timeout for live model providers.

    Honors ``CHRONICLE_MODEL_TIMEOUT_SECONDS`` from the given mapping
    (or the process environment when omitted). All production model entries
    use this value; the staged transport also uses it for its wall-clock
    deadline, without a separate step/profile cap.
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
            "CHRONICLE_MODEL_TIMEOUT_SECONDS must be a finite positive number"
        ) from exc
    if not math.isfinite(value) or value <= 0:
        raise PersistenceError(
            "CHRONICLE_MODEL_TIMEOUT_SECONDS must be a finite positive number"
        )
    return value


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
    timeout_seconds: float = field(default_factory=timeout_from_env)
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    max_attempts: int = DEFAULT_MODEL_MAX_ATTEMPTS
    retry_backoff_seconds: float = DEFAULT_MODEL_RETRY_BACKOFF_SECONDS
    text_format: dict[str, Any] | None = None
    # Chapter output budget (chapter-production §3 / T01 ChapterLimits).
    # Current chapter profiles set this explicitly; other transports may omit it.
    max_output_tokens: int | None = None
    # Worker-local contract metadata; never sent as a provider payload field.
    # The chapter factory binds this to the same version as text_format.
    candidate_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise PersistenceError("model name must be a non-empty string")
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "endpoint", _validate_endpoint(self.endpoint))
        if (not isinstance(self.timeout_seconds, (int, float))
                or isinstance(self.timeout_seconds, bool)
                or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0):
            raise PersistenceError("model timeout must be a finite positive number")
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

    def complete_with_receipt(self, prompt: str, *, on_progress=None,
                              cancelled=None) -> tuple[str, dict]:
        """One observable HTTP attempt with an actual wall-clock deadline.

        The staged scheduler owns retries and persists each attempt. Use an
        interruptible async transport here so a peer sending keep-alive bytes
        cannot reset the global timeout indefinitely. Network inactivity and
        the wall-clock deadline both use ``self.timeout_seconds``. Raw
        reasoning/envelopes are never returned to the product audit log.
        """
        if not isinstance(prompt, str) or not prompt:
            raise ModelProviderError("model prompt must be a non-empty string")
        try:
            import httpx
        except ImportError as exc:
            raise PersistenceError("install apps/chronicle/worker/requirements.txt for staged model transport") from exc
        started = time.monotonic()
        receipt: dict[str, Any] = {
            "requested_model": self.name, "model": None, "status": "started",
            "usage": None, "http_attempts": 1, "response_bytes": 0,
            "elapsed_seconds": 0.0, "incomplete_reason": None,
            "timeout_seconds": self.timeout_seconds,
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
            return await asyncio.wait_for(perform_cancellable(), timeout=self.timeout_seconds)

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
            raise ModelProviderError(
                f"model attempt exceeded CHRONICLE_MODEL_TIMEOUT_SECONDS ({self.timeout_seconds:g}s)",
                receipt=receipt, raw_text=raw_text) from exc
        except httpx.HTTPError as exc:
            receipt["status"] = "transport_error"
            raise ModelProviderError("model endpoint transport failure", receipt=receipt, raw_text=raw_text) from exc
        except ModelProviderError as exc:
            if receipt["status"] in ("started", "completed", None):
                receipt["status"] = "failed"
            raise ModelProviderError(str(exc), receipt=receipt, raw_text=raw_text) from exc
        finally:
            receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)
