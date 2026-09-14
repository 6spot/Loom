"""Frozen provider profiles for the historical narrative step graph."""
from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass, replace
from typing import Mapping
from urllib.parse import urlsplit

import narrative_contract as contract
import narrative_model_settings as settings
from common import PersistenceConflict, PersistenceError, sha256_json
from model_provider import ResponsesHTTPModel, _validate_endpoint, timeout_from_env


MAX_OUTPUT_TOKENS = 65536


def _integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise PersistenceError(f"{label} must be an integer in {minimum}..{maximum}")
    return value


@dataclass(frozen=True)
class NarrativeModels:
    """Provider-neutral model choices used by the narrative adapter.

    ``steps`` is immutable from a caller's point of view.  A Studio selection
    creates a replacement instance, so an active job never silently adopts a
    later model choice.
    """

    name: str
    profiles: dict[str, dict]
    steps: dict[str, tuple[str, ...]]
    providers: dict[tuple[str, str], object]
    max_parallel: int = 2
    max_step_attempts: int = 3
    candidate_version: str = contract.VERSION
    selection_key: str | None = None

    @property
    def timeout_seconds(self) -> float:
        return next(iter(self.profiles.values()))["timeout_seconds"]

    @property
    def max_response_bytes(self) -> int:
        return next(iter(self.profiles.values()))["max_response_bytes"]

    @property
    def max_output_tokens(self) -> int:
        return next(iter(self.profiles.values()))["max_output_tokens"]

    def complete(self, _prompt: str) -> str:
        raise PersistenceError(
            "narrative model configuration must execute through the durable step entry"
        )

    def model_for(self, step: str, slot: str):
        step = settings.STEP_ALIASES.get(step, step)
        try:
            return self.providers[(step, slot)]
        except KeyError as exc:
            raise PersistenceError(f"narrative step {step}/{slot} has no configured provider") from exc

    def config_for(self, step: str, slot: str) -> dict:
        step = settings.STEP_ALIASES.get(step, step)
        if slot not in self.profiles:
            raise PersistenceError(f"unknown narrative model profile {slot!r}")
        profile = self.profiles[slot]
        return {
            **profile,
            "schema_sha256": sha256_json(contract.step_schema(step)),
        }

    def public_config(self) -> dict:
        return {
            "version": settings.VERSION,
            "candidate_version": self.candidate_version,
            "models": copy.deepcopy(self.profiles),
            "steps": {key: list(value) for key, value in self.steps.items()},
            "step_definitions": {
                step: {"dependencies": [], "retryable": True}
                for step in settings.STEPS
            },
            "max_parallel": self.max_parallel,
            "max_step_attempts": self.max_step_attempts,
            "schemas": {
                step: sha256_json(contract.step_schema(step)) for step in settings.STEPS
            },
            "prompt_templates": {
                step: sha256_json(contract.prompt_template_text(step)) for step in settings.STEPS
            },
            "retry_template": sha256_json(contract.retry_template()),
        }

    def for_selection(self, selection: object) -> "NarrativeModels":
        if not isinstance(selection, dict) or selection.get("config_sha256") != self.selection_key:
            raise PersistenceConflict(
                "model_configuration_changed: task narrative model choices no longer match worker configuration"
            )
        selected = settings.normalize_steps(selection.get("steps"), self.profiles)
        return replace(self, steps={step: tuple(slots) for step, slots in selected.items()})


def from_env(env: Mapping[str, str] | None = None) -> NarrativeModels | None:
    values = dict(os.environ if env is None else env)
    primary = str(values.get("CHRONICLE_NARRATIVE_MODEL") or "").strip()
    config_path = str(values.get("CHRONICLE_NARRATIVE_PIPELINE_CONFIG") or "").strip()
    if not primary and not config_path:
        return None
    config = settings.load_config(values)
    timeout = timeout_from_env(values)
    safe: dict[str, dict] = {}
    keys: dict[str, str | None] = {}
    for slot, profile in config["models"].items():
        if not isinstance(profile, dict):
            raise PersistenceError("invalid narrative model profile")
        if {"timeout_seconds", "total_timeout_seconds"} & set(profile):
            raise PersistenceError(
                "narrative model timeouts are global; remove timeout_seconds/total_timeout_seconds "
                "and set CHRONICLE_MODEL_TIMEOUT_SECONDS"
            )
        allowed = {"model", "endpoint", "api_key_env", "max_output_tokens", "response_format"}
        if set(profile) - allowed:
            raise PersistenceError("invalid narrative model profile; credentials must use api_key_env")
        name = profile.get("model")
        if not isinstance(name, str) or not name.strip():
            raise PersistenceError("every narrative model profile must name its actual model")
        if name.strip().startswith("fixture:"):
            raise PersistenceError(
                "retired narrative fixture providers are unsupported; configure the production provider"
            )
        endpoint = profile.get("endpoint") or values.get("CHRONICLE_MODEL_ENDPOINT") or ""
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise PersistenceError(
                "CHRONICLE_MODEL_ENDPOINT or a profile endpoint is required for the historical narrative model"
            )
        endpoint = _validate_endpoint(endpoint)
        parsed = urlsplit(endpoint)
        if parsed.query or parsed.fragment:
            raise PersistenceError(
                "narrative model endpoint must not contain a query or fragment; use api_key_env"
            )
        key_env = profile.get("api_key_env", "CHRONICLE_MODEL_API_KEY")
        if not isinstance(key_env, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key_env):
            raise PersistenceError("api_key_env must name an environment variable")
        output = _integer(
            profile.get("max_output_tokens", 32768),
            "max_output_tokens",
            1,
            MAX_OUTPUT_TOKENS,
        )
        response_format = profile.get("response_format", "json_object")
        if response_format != "json_object":
            raise PersistenceError("narrative response_format must be json_object")
        safe[slot] = {
            "model": name.strip(),
            "endpoint": endpoint,
            "api_key_env": key_env,
            "timeout_seconds": timeout,
            "max_output_tokens": output,
            "max_response_bytes": contract.MAX_BYTES,
            "response_format": response_format,
        }
        keys[slot] = values.get(key_env) or None

    steps = settings.normalize_steps(config["steps"], safe)
    providers: dict[tuple[str, str], object] = {}
    for step in settings.STEPS:
        for slot in safe:
            profile = safe[slot]
            providers[(step, slot)] = ResponsesHTTPModel(
                name=profile["model"],
                endpoint=profile["endpoint"],
                api_key=keys[slot],
                timeout_seconds=timeout,
                max_output_tokens=profile["max_output_tokens"],
                max_response_bytes=profile["max_response_bytes"],
                max_attempts=1,
                text_format={"type": "json_object"},
                candidate_version=contract.VERSION,
            )
    return NarrativeModels(
        name=primary or safe[next(iter(safe))]["model"],
        profiles=safe,
        steps={step: tuple(slots) for step, slots in steps.items()},
        providers=providers,
        max_parallel=_integer(config.get("max_parallel", 2), "max_parallel", 1, 4),
        max_step_attempts=_integer(config.get("max_step_attempts", 3), "max_step_attempts", 1, 3),
        selection_key=settings.config_key(config, values),
    )


__all__ = ["NarrativeModels", "from_env"]
