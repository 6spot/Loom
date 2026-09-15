"""Credential-free model selection for Chronicle's historical narrative job.

The chapter pipeline has its own settings module because it has six staged
steps.  Narrative production deliberately keeps a smaller, explicit graph:
generation and comparison are independently configurable for facts and prose.
The worker resolves endpoints and credentials; this module only validates the
selection that Studio may freeze into a job.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Mapping

from common import PersistenceConflict, PersistenceError, sha256_json


VERSION = "0.1"
STEPS = ("facts_generate", "facts_compare", "prose_generate", "prose_compare")
STEP_ALIASES = {
    "facts": "facts_generate",
    "prose": "prose_generate",
    "facts_review": "facts_compare",
    "facts_compare/review": "facts_compare",
    "prose_review": "prose_compare",
    "prose_compare/review": "prose_compare",
}


def _split_models(raw: object, *, fallback: str | None, label: str) -> list[str]:
    value = str(raw or "")
    names = [item.strip() for item in value.split(",") if item.strip()]
    if not names and fallback:
        names = [fallback]
    if not names or len(names) > 4:
        raise PersistenceError(f"{label} must name 1..4 models")
    if len(set(names)) != len(names):
        raise PersistenceError(f"{label} repeats a model name")
    return names


def _read_file(path: str) -> dict:
    try:
        raw = Path(path).read_bytes()
        if len(raw) > 65536:
            raise PersistenceError("narrative model config exceeds 64 KiB")
        value = json.loads(raw)
    except PersistenceError:
        raise
    except (OSError, ValueError) as exc:
        raise PersistenceError("narrative model config must be a readable JSON document") from exc
    if not isinstance(value, dict):
        raise PersistenceError("narrative model config must be a JSON object")
    return value


def _normalize_step_keys(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise PersistenceError("narrative model selection must define all four steps")
    normalized = {}
    for key, value in raw.items():
        target = STEP_ALIASES.get(key, key)
        if target in normalized:
            raise PersistenceError(f"narrative model selection repeats {target}")
        normalized[target] = value
    if set(normalized) != set(STEPS):
        raise PersistenceError("narrative model selection must define all four steps")
    return normalized


def normalize_steps(steps: object, profiles: Mapping[str, object]) -> dict[str, list[str]]:
    normalized = _normalize_step_keys(steps)
    result: dict[str, list[str]] = {}
    for step in STEPS:
        slots = normalized[step]
        if (
            not isinstance(slots, list)
            or not 1 <= len(slots) <= 4
            or any(not isinstance(slot, str) or not slot for slot in slots)
            or len(set(slots)) != len(slots)
            or any(slot not in profiles for slot in slots)
        ):
            raise PersistenceError(f"{step} must name 1..4 unique configured model profiles")
        result[step] = list(slots)
    return result


def _profile_name(name: str, used: set[str], prefix: str) -> str:
    candidate = prefix
    index = 1
    while candidate in used:
        index += 1
        candidate = f"{prefix}_{index}"
    used.add(candidate)
    return candidate


def load_config(env: Mapping[str, str]) -> dict:
    path = str(env.get("CHRONICLE_NARRATIVE_PIPELINE_CONFIG") or "").strip()
    primary = str(env.get("CHRONICLE_NARRATIVE_MODEL") or "").strip()
    if path:
        config = _read_file(path)
    else:
        if not primary:
            raise PersistenceError(
                "CHRONICLE_NARRATIVE_MODEL or CHRONICLE_NARRATIVE_PIPELINE_CONFIG is required"
            )
        facts = _split_models(
            env.get("CHRONICLE_NARRATIVE_FACTS_MODELS"),
            fallback=primary,
            label="CHRONICLE_NARRATIVE_FACTS_MODELS",
        )
        prose = _split_models(
            env.get("CHRONICLE_NARRATIVE_PROSE_MODELS"),
            fallback=primary,
            label="CHRONICLE_NARRATIVE_PROSE_MODELS",
        )
        comparators = _split_models(
            env.get("CHRONICLE_NARRATIVE_COMPARE_MODELS")
            or env.get("CHRONICLE_NARRATIVE_REVIEW_MODELS"),
            fallback=primary,
            label="CHRONICLE_NARRATIVE_COMPARE_MODELS",
        )
        names: dict[str, dict] = {}
        by_model: dict[str, str] = {}
        used: set[str] = set()

        def slot_for(name: str, prefix: str) -> str:
            if name in by_model:
                return by_model[name]
            if not used:
                slot = "executor"
                used.add(slot)
            else:
                slot = _profile_name(name, used, prefix)
            by_model[name] = slot
            names[slot] = {"model": name}
            return slot

        facts_slots = [slot_for(name, "facts_generator") for name in facts]
        prose_slots = [slot_for(name, "prose_generator") for name in prose]
        compare_slots = [slot_for(name, "comparator") for name in comparators]
        config = {
            "version": VERSION,
            "models": names,
            "steps": {
                "facts_generate": facts_slots,
                "facts_compare": compare_slots,
                "prose_generate": prose_slots,
                "prose_compare": compare_slots,
            },
        }

    if not isinstance(config, dict) or config.get("version") != VERSION:
        raise PersistenceError("unsupported narrative pipeline configuration")
    allowed = {"version", "models", "steps", "max_parallel", "max_step_attempts"}
    if set(config) - allowed:
        raise PersistenceError("unsupported narrative pipeline configuration")
    profiles = config.get("models")
    if not isinstance(profiles, dict) or not 1 <= len(profiles) <= 12:
        raise PersistenceError("narrative config must define 1..12 model profiles")
    for slot, profile in profiles.items():
        if (
            not isinstance(slot, str)
            or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", slot)
            or not isinstance(profile, dict)
            or not isinstance(profile.get("model"), str)
            or not profile["model"].strip()
        ):
            raise PersistenceError("every narrative model profile must have an ID and actual model name")
    normalize_steps(config.get("steps"), profiles)
    for key, minimum, maximum in (("max_parallel", 1, 4), ("max_step_attempts", 1, 3)):
        value = config.get(key, 2 if key == "max_parallel" else 3)
        if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
            raise PersistenceError(f"{key} must be an integer in {minimum}..{maximum}")
    return config


def config_key(config: dict, env: Mapping[str, str]) -> str:
    # Credentials and timeout values are intentionally excluded.  The worker
    # freezes the effective timeout in its public config separately.
    return sha256_json({
        "config": config,
        "endpoint": env.get("CHRONICLE_MODEL_ENDPOINT") or "",
    })


def catalog(env: Mapping[str, str]) -> dict:
    primary = str(env.get("CHRONICLE_NARRATIVE_MODEL") or "").strip()
    if not primary and not str(env.get("CHRONICLE_NARRATIVE_PIPELINE_CONFIG") or "").strip():
        return {"available": False, "models": [], "steps": {}, "config_sha256": None}
    config = load_config(env)
    if any(
        isinstance(profile, dict)
        and isinstance(profile.get("model"), str)
        and profile["model"].strip().startswith("fixture:")
        for profile in config["models"].values()
    ):
        return {"available": False, "models": [], "steps": {}, "config_sha256": None}
    return {
        "available": True,
        "config_sha256": config_key(config, env),
        "models": [
            {"id": slot, "name": profile["model"].strip()}
            for slot, profile in config["models"].items()
        ],
        "steps": normalize_steps(config["steps"], config["models"]),
    }


def validate_selection(value: object, choices: dict) -> dict:
    if not isinstance(value, dict) or set(value) != {"config_sha256", "steps"}:
        raise PersistenceError("narrative model selection requires config_sha256 and steps")
    if not choices.get("available") or value["config_sha256"] != choices["config_sha256"]:
        raise PersistenceConflict(
            "model_configuration_changed: refresh narrative model choices before creating a task"
        )
    slots = {model["id"] for model in choices["models"]}
    return {
        "config_sha256": value["config_sha256"],
        "steps": normalize_steps(value["steps"], {slot: {} for slot in slots}),
    }


__all__ = [
    "STEPS",
    "VERSION",
    "catalog",
    "config_key",
    "load_config",
    "normalize_steps",
    "validate_selection",
]
