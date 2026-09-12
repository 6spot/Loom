"""Frozen per-step model configuration for the one chapter worker entry."""
from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chapter_production as protocol
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
                "max_parallel": self.max_parallel, "max_step_attempts": self.max_step_attempts,
                "max_repair_rounds": self.max_repair_rounds,
                "schemas": {step: sha256_json(protocol.step_schema(step)) for step in protocol.STEPS}}

    def config_for(self, step: str, slot: str) -> dict:
        return {**self.profiles[slot], "response_format": "text" if step == "translation"
                else self.profiles[slot]["response_format"],
                "schema_sha256": sha256_json(protocol.step_schema(step))}

    def model_for(self, step: str, slot: str):
        return self.providers[(step, slot)]


def _integer(value, label, minimum, maximum):
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise PersistenceError(f"{label} must be an integer in {minimum}..{maximum}")
    return value


def _seconds(value, label):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or not 0 < value <= 1800:
        raise PersistenceError(f"{label} must be a finite positive number at most 1800")
    return float(value)


def from_env(env, *, limits) -> ChapterModels:
    """Names/endpoints are configuration; credential values never enter a hash."""
    config_path = str(env.get("CHRONICLE_CHAPTER_PIPELINE_CONFIG") or "").strip()
    primary = str(env.get("CHRONICLE_CHAPTER_MODEL") or "").strip()
    if config_path:
        try:
            raw = Path(config_path).read_bytes()
            if len(raw) > 65536:
                raise PersistenceError("chapter model config exceeds 64 KiB")
            config = json.loads(raw)
        except (OSError, ValueError) as exc:
            raise PersistenceError("chapter model config must be a readable JSON document") from exc
    else:
        if not primary:
            raise PersistenceError("CHRONICLE_CHAPTER_MODEL or CHRONICLE_CHAPTER_PIPELINE_CONFIG is required")
        review_names = [name.strip() for name in str(
            env.get("CHRONICLE_CHAPTER_REVIEW_MODELS") or primary).split(",") if name.strip()]
        profiles = {"executor": {"model": primary}}
        reviewer_ids = []
        for index, name in enumerate(review_names, 1):
            slot = f"reviewer_{index}"
            profiles[slot] = {"model": name}
            reviewer_ids.append(slot)
        config = {"version": "0.1", "models": profiles,
                  "steps": {step: reviewer_ids if step in ("review", "comparison") else ["executor"]
                            for step in protocol.STEPS}}
    if not isinstance(config, dict) or config.get("version") != "0.1" or set(config) - {
        "version", "models", "steps", "max_parallel", "max_step_attempts", "max_repair_rounds"}:
        raise PersistenceError("unsupported chapter pipeline configuration")
    profiles = config.get("models")
    steps = config.get("steps")
    if not isinstance(profiles, dict) or not 1 <= len(profiles) <= 12 or not isinstance(steps, dict) or set(steps) != set(protocol.STEPS):
        raise PersistenceError("chapter config must define 1..12 model profiles and all six steps")
    safe = {}
    keys = {}
    for slot, profile in profiles.items():
        if not isinstance(slot, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", slot) or not isinstance(profile, dict) or set(profile) - {
            "model", "endpoint", "api_key_env", "timeout_seconds", "total_timeout_seconds",
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
        timeout = _seconds(profile.get("timeout_seconds", timeout_from_env(env)), "timeout_seconds")
        total = _seconds(profile.get("total_timeout_seconds", min(timeout, 360)), "total_timeout_seconds")
        output = _integer(profile.get("max_output_tokens", limits.max_output_tokens), "max_output_tokens", 1, limits.max_output_tokens)
        response_format = profile.get("response_format", "json_object")
        if response_format not in ("json_object", "text"):
            raise PersistenceError("response_format must be json_object or text")
        safe[slot] = {"model": name.strip(), "endpoint": endpoint, "api_key_env": key_env,
                      "timeout_seconds": timeout, "total_timeout_seconds": total,
                      "max_output_tokens": output, "max_response_bytes": limits.max_response_bytes,
                      "response_format": response_format}
        keys[slot] = env.get(key_env) or None
    selected = {}
    providers = {}
    for step in protocol.STEPS:
        slots = steps[step]
        if (not isinstance(slots, list) or not 1 <= len(slots) <= 4
                or any(not isinstance(slot, str) for slot in slots)
                or len(set(slots)) != len(slots) or any(slot not in safe for slot in slots)):
            raise PersistenceError(f"{step} must name 1..4 unique configured model profiles")
        selected[step] = tuple(slots)
        for slot in slots:
            profile = safe[slot]
            providers[(step, slot)] = ResponsesHTTPModel(
                name=profile["model"], endpoint=profile["endpoint"], api_key=keys[slot],
                timeout_seconds=profile["timeout_seconds"], max_output_tokens=profile["max_output_tokens"],
                max_response_bytes=profile["max_response_bytes"], max_attempts=1,
                text_format=None if step == "translation" or profile["response_format"] == "text"
                else {"type": "json_object"}, candidate_version="0.4")
    return ChapterModels(
        name=primary or safe[next(iter(profiles))]["model"], profiles=safe, steps=selected,
        providers=providers, max_parallel=_integer(config.get("max_parallel", 2), "max_parallel", 1, 4),
        max_step_attempts=_integer(config.get("max_step_attempts", 2), "max_step_attempts", 1, 3),
        max_repair_rounds=_integer(config.get("max_repair_rounds", 1), "max_repair_rounds", 0, 1))
