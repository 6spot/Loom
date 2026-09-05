"""Deployment model provider boundary for Chronicle ingestion workers.

C1-T13 needs the already-tested C1 extraction/presentation provider protocols
to be reachable from the real Docker worker. This module intentionally keeps
that deployment I/O vendor-neutral: it speaks the small HTTP subset used by a
Responses-style endpoint (``POST`` JSON with ``model`` + ``input``) and returns
only the produced text.

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
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request

from common import PersistenceError

DEFAULT_MODEL_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MODEL_HTTP_USER_AGENT = "Loom-Chronicle/0.1"


class ModelProviderError(RuntimeError):
    """Raised when the configured model endpoint cannot produce valid text."""


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


def _timeout_from_env() -> float:
    raw = _nonempty_env("CHRONICLE_MODEL_TIMEOUT_SECONDS")
    if raw is None:
        return DEFAULT_MODEL_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError as exc:
        raise PersistenceError(
            "CHRONICLE_MODEL_TIMEOUT_SECONDS must be a positive number"
        ) from exc
    if value <= 0:
        raise PersistenceError(
            "CHRONICLE_MODEL_TIMEOUT_SECONDS must be a positive number"
        )
    return value


def _response_text(payload: Any) -> str:
    """Extract generated text from a Responses-style JSON object."""
    if not isinstance(payload, dict):
        raise ModelProviderError("model response must be a JSON object")

    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct

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

    joined = "".join(parts)
    if joined.strip():
        return joined
    raise ModelProviderError("model response contains no output text")


@dataclass(frozen=True)
class ResponsesHTTPModel:
    """Small synchronous provider implementing Chronicle's ``complete`` hook."""

    name: str
    endpoint: str
    api_key: str | None = None
    timeout_seconds: float = DEFAULT_MODEL_TIMEOUT_SECONDS
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise PersistenceError("model name must be a non-empty string")
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "endpoint", _validate_endpoint(self.endpoint))
        if self.timeout_seconds <= 0:
            raise PersistenceError("model timeout must be positive")
        if self.max_response_bytes < 1:
            raise PersistenceError("model max_response_bytes must be positive")

    def complete(self, prompt: str) -> str:
        if not isinstance(prompt, str) or not prompt:
            raise ModelProviderError("model prompt must be a non-empty string")

        body = json.dumps(
            {"model": self.name, "input": prompt},
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
            # Do not echo a response body: gateways may include request details,
            # credentials, or source text in their diagnostics.
            raise ModelProviderError(
                f"model endpoint returned HTTP {exc.code}"
            ) from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            raise ModelProviderError("model endpoint request failed") from exc

        if len(raw) > self.max_response_bytes:
            raise ModelProviderError("model response exceeds configured size limit")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelProviderError("model endpoint returned invalid JSON") from exc
        return _response_text(payload)


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

    def build(name: str | None) -> ResponsesHTTPModel | None:
        if name is None:
            return None
        return ResponsesHTTPModel(
            name=name,
            endpoint=endpoint,
            api_key=api_key,
            timeout_seconds=timeout,
        )

    return build(extraction_name), build(presentation_name)
