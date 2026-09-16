"""Frozen per-step model configuration for the one chapter worker entry."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, replace
from typing import Any

import chapter_production as protocol
import chapter_model_settings as settings
from common import PersistenceError, sha256_json
from model_provider import ResponsesHTTPModel, _validate_endpoint, timeout_from_env


@dataclass(frozen=True)
class ChapterModels:
    name: str
    profiles: dict[str, dict]
    steps: dict[str, tuple[str, ...]]
    providers: dict[tuple[str, str], Any]
    max_parallel: int = 2
    max_step_attempts: int = 2
    max_repair_rounds: int = 1
    candidate_version: str = "0.4"
    selection_key: str | None = None

    @property
    def timeout_seconds(self):
        return next(iter(self.profiles.values()))["timeout_seconds"]

    @property
    def max_response_bytes(self):
        return next(iter(self.profiles.values()))["max_response_bytes"]

    @property
    def max_output_tokens(self):
        return next(iter(self.profiles.values()))["max_output_tokens"]

    def complete(self, prompt):
        raise PersistenceError("staged chapter configuration must execute through the durable chapter entry")

    def public_config(self) -> dict:
        return {"version": protocol.VERSION, "models": copy.deepcopy(self.profiles),
                "steps": {key: list(value) for key, value in self.steps.items()},
                "step_definitions": {
                    key: {
                        "dependencies": list(definition.dependencies),
                        "retryable": definition.retryable,
                    }
                    for key, definition in protocol.STEP_DEFINITIONS.items()
                },
                "max_parallel": self.max_parallel, "max_step_attempts": self.max_step_attempts,
                "max_repair_rounds": self.max_repair_rounds,
                "format_retry_steps": list(protocol.FORMAT_RETRY_STEPS),
                "schemas": {step: sha256_json(protocol.step_schema(step)) for step in protocol.STEPS},
                "provider_schemas": {
                    step: sha256_json(protocol.provider_schema(step))
                    for step in protocol.STEPS
                },
                # Render the actual template with empty, deterministic data:
                # prompt wording/wrapper changes must also freeze the whole
                # job, even when its output schema and model names are equal.
                "prompt_templates": {step: sha256_json(protocol.build_prompt(
                    step, {}, {}, max_chars=1048576)) for step in protocol.STEPS},
                "retry_template": sha256_json(protocol.retry_prompt("", {}, max_chars=1048576))}

    def config_for(self, step: str, slot: str) -> dict:
        return {**self.profiles[slot], "response_format": "text" if step == "translation"
                else self.profiles[slot]["response_format"],
                "schema_sha256": sha256_json(protocol.step_schema(step)),
                "provider_schema_sha256": sha256_json(protocol.provider_schema(step))}

    def for_selection(self, selection):
        if not isinstance(selection, dict) or selection.get("config_sha256") != self.selection_key:
            from common import PersistenceConflict
            raise PersistenceConflict("model_configuration_changed: task model choices no longer match worker configuration")
        steps = settings.normalize_steps(selection.get("steps"), self.profiles)
        return replace(self, steps={step: tuple(slots) for step, slots in steps.items()})

    def model_for(self, step: str, slot: str):
        return self.providers[(step, slot)]


def _integer(value, label, minimum, maximum):
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise PersistenceError(f"{label} must be an integer in {minimum}..{maximum}")
    return value


def from_env(env, *, limits) -> ChapterModels:
    """Names/endpoints are configuration; credential values never enter a hash."""
    primary = str(env.get("CHRONICLE_CHAPTER_MODEL") or "").strip()
    if primary.startswith("fixture:"):
        raise PersistenceError(
            "retired chapter fixture providers are unsupported; configure the staged provider"
        )
    config = settings.load_config(env)
    profiles = config.get("models")
    steps = config.get("steps")
    if not isinstance(profiles, dict) or not 1 <= len(profiles) <= 12 or not isinstance(steps, dict) or set(steps) != set(protocol.STEPS):
        raise PersistenceError("chapter config must define 1..12 model profiles and all six steps")
    timeout = timeout_from_env(env)
    safe = {}
    keys = {}
    for slot, profile in profiles.items():
        if isinstance(profile, dict) and {"timeout_seconds", "total_timeout_seconds"} & set(profile):
            raise PersistenceError(
                "model timeouts are global; remove timeout_seconds/total_timeout_seconds "
                "from model profiles and set CHRONICLE_MODEL_TIMEOUT_SECONDS")
        if not isinstance(slot, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", slot) or not isinstance(profile, dict) or set(profile) - {
            "model", "endpoint", "api_key_env",
            "max_output_tokens", "response_format"}:
            raise PersistenceError("invalid model profile; credentials must use api_key_env")
        name = profile.get("model")
        if not isinstance(name, str) or not name.strip():
            raise PersistenceError("every model profile must name its actual model")
        endpoint = profile.get("endpoint") or env.get("CHRONICLE_MODEL_ENDPOINT") or ""
        if not isinstance(endpoint, str):
            raise PersistenceError("model endpoint must be an absolute http(s) URL")
        endpoint = _validate_endpoint(endpoint)
        # Secrets in query parameters would enter the frozen public config.
        from urllib.parse import urlsplit
        if urlsplit(endpoint).query or urlsplit(endpoint).fragment:
            raise PersistenceError("model endpoint must not contain a query or fragment; use api_key_env")
        key_env = profile.get("api_key_env", "CHRONICLE_MODEL_API_KEY")
        if not isinstance(key_env, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key_env):
            raise PersistenceError("api_key_env must name an environment variable")
        output = _integer(profile.get("max_output_tokens", limits.max_output_tokens), "max_output_tokens", 1, limits.max_output_tokens)
        response_format = profile.get("response_format", "json_object")
        if response_format not in ("json_object", "text"):
            raise PersistenceError("response_format must be json_object or text")
        safe[slot] = {"model": name.strip(), "endpoint": endpoint, "api_key_env": key_env,
                      # Effective global value, retained only for the audit snapshot.
                      "timeout_seconds": timeout,
                      "max_output_tokens": output, "max_response_bytes": limits.max_response_bytes,
                      "response_format": response_format}
        keys[slot] = env.get(key_env) or None
    selected = {step: tuple(slots) for step, slots in settings.normalize_steps(steps, safe).items()}
    providers = {}
    for step in protocol.STEPS:
        # Providers are lightweight, lazy HTTP adapters. Build all configured
        # choices so per-job selection never mutates the worker defaults.
        for slot in safe:
            profile = safe[slot]
            providers[(step, slot)] = ResponsesHTTPModel(
                name=profile["model"], endpoint=profile["endpoint"], api_key=keys[slot],
                timeout_seconds=timeout, max_output_tokens=profile["max_output_tokens"],
                max_response_bytes=profile["max_response_bytes"], max_attempts=1,
                text_format=None if step == "translation" or profile["response_format"] == "text"
                else protocol.provider_text_format(step), candidate_version="0.4")
    return ChapterModels(
        name=primary or safe[next(iter(profiles))]["model"], profiles=safe, steps=selected,
        selection_key=settings.config_key(config, env),
        providers=providers, max_parallel=_integer(config.get("max_parallel", 2), "max_parallel", 1, 4),
        max_step_attempts=_integer(config.get("max_step_attempts", 2), "max_step_attempts", 1, 3),
        max_repair_rounds=_integer(config.get("max_repair_rounds", 1), "max_repair_rounds", 0, 1))
