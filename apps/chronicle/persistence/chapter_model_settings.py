"""Shared, credential-free model choices for Studio and the chapter worker.

Studio selects existing profile IDs; it cannot provide endpoints, credentials,
timeouts or new execution budgets. The worker still owns provider validation.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import chapter_production
from common import PersistenceConflict, PersistenceError, sha256_json


def load_config(env) -> dict:
    path = str(env.get("CHRONICLE_CHAPTER_PIPELINE_CONFIG") or "").strip()
    primary = str(env.get("CHRONICLE_CHAPTER_MODEL") or "").strip()
    if path:
        try:
            raw = Path(path).read_bytes()
            if len(raw) > 65536:
                raise PersistenceError("chapter model config exceeds 64 KiB")
            config = json.loads(raw)
        except (OSError, ValueError) as exc:
            raise PersistenceError("chapter model config must be a readable JSON document") from exc
    else:
        if not primary:
            raise PersistenceError("CHRONICLE_CHAPTER_MODEL or CHRONICLE_CHAPTER_PIPELINE_CONFIG is required")
        reviewers = [name.strip() for name in str(env.get("CHRONICLE_CHAPTER_REVIEW_MODELS") or primary).split(",") if name.strip()]
        models = {"executor": {"model": primary}}
        ids = []
        for index, name in enumerate(reviewers, 1):
            slot = f"reviewer_{index}"
            models[slot] = {"model": name}
            ids.append(slot)
        config = {"version": "0.1", "models": models,
                  "steps": {step: ids if step in ("review", "comparison") else ["executor"]
                            for step in chapter_production.STEPS}}
    if not isinstance(config, dict) or config.get("version") != "0.1" or set(config) - {
        "version", "models", "steps", "max_parallel", "max_step_attempts", "max_repair_rounds"}:
        raise PersistenceError("unsupported chapter pipeline configuration")
    models = config.get("models")
    if not isinstance(models, dict) or not 1 <= len(models) <= 12:
        raise PersistenceError("chapter config must define 1..12 model profiles")
    for slot, profile in models.items():
        if (not isinstance(slot, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", slot)
                or not isinstance(profile, dict) or not isinstance(profile.get("model"), str)
                or not profile["model"].strip()):
            raise PersistenceError("every model profile must have an ID and actual model name")
    normalize_steps(config.get("steps"), models)
    return config


def normalize_steps(steps, profiles) -> dict[str, list[str]]:
    if not isinstance(steps, dict) or set(steps) != set(chapter_production.STEPS):
        raise PersistenceError("model selection must define all six steps")
    result = {}
    for step in chapter_production.STEPS:
        slots = steps[step]
        if (not isinstance(slots, list) or not 1 <= len(slots) <= 4
                or any(not isinstance(slot, str) for slot in slots)
                or len(set(slots)) != len(slots) or any(slot not in profiles for slot in slots)):
            raise PersistenceError(f"{step} must name 1..4 unique configured model profiles")
        result[step] = list(slots)
    return result


def config_key(config, env) -> str:
    # Credential VALUES and transport timeout are not model-choice identity.
    # The full effective execution config is frozen separately by the worker.
    return sha256_json({"config": config, "endpoint": env.get("CHRONICLE_MODEL_ENDPOINT") or ""})


def catalog(env) -> dict:
    fixture = str(env.get("CHRONICLE_CHAPTER_MODEL") or "").startswith("fixture:")
    if env.get("CHRONICLE_CHAPTER_FIXTURE_PACK") or (fixture and not env.get("CHRONICLE_CHAPTER_PIPELINE_CONFIG")) or not (
        env.get("CHRONICLE_CHAPTER_MODEL") or env.get("CHRONICLE_CHAPTER_PIPELINE_CONFIG")
    ):
        return {"available": False, "models": [], "steps": {}, "config_sha256": None}
    config = load_config(env)
    return {"available": True, "config_sha256": config_key(config, env),
            "models": [{"id": slot, "name": profile["model"].strip()} for slot, profile in config["models"].items()],
            "steps": normalize_steps(config["steps"], config["models"])}


def validate_selection(value, choices) -> dict:
    if not isinstance(value, dict) or set(value) != {"config_sha256", "steps"}:
        raise PersistenceError("model selection requires config_sha256 and steps")
    if not choices.get("available") or value["config_sha256"] != choices["config_sha256"]:
        raise PersistenceConflict("model_configuration_changed: refresh model choices before creating a task")
    return {"config_sha256": value["config_sha256"],
            "steps": normalize_steps(value["steps"], {model["id"] for model in choices["models"]})}
