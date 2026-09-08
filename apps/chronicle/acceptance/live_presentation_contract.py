#!/usr/bin/env python3
"""Real Reader-provider preflight on retained C0 knowledge in an isolated DB.

This is not T17 acceptance. It exercises the production context loader,
generator, validators and immutable persistence for Entity and Event targets
before an operator spends time on a fresh real-source review. Only bounded
metadata/hashes/counts are printed, never prompts, model text or credentials.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

import psycopg
from jsonschema import Draft202012Validator, FormatChecker
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

CHRONICLE = Path(__file__).resolve().parent.parent
for path in (CHRONICLE / "persistence", CHRONICLE / "worker"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import model_provider  # noqa: E402
import presentation as P  # noqa: E402
from common import load_json  # noqa: E402
from migrations import apply_migrations  # noqa: E402
from postgres_v0 import persist_dataset  # noqa: E402
from presentation_model_schema import CANONICAL_SCHEMA  # noqa: E402

ARTIFACTS = CHRONICLE / ".artifacts" / "c0-t7"
# Existing T12 manually inspected historical examples, resolved through the
# retained canonical catalog rather than invented canonical identities.
TARGETS = (("entity", "wudi", "ent_002"), ("event", "wudi", "evt_022"))


class RecordedModel:
    def __init__(self, provider):
        self.provider = provider
        self.name = provider.name
        self.raw = ""

    def complete(self, prompt: str) -> str:
        self.raw = self.provider.complete(prompt)
        return self.raw


def verify(database_url: str, provider) -> list[dict]:
    bundles = {label: load_json(ARTIFACTS / label / "final.json") for label in ("wudi", "wuzhu")}
    catalog = load_json(ARTIFACTS / "publication" / "catalog.json")
    with psycopg.connect(database_url) as conn:
        apply_migrations(conn)
        persist_dataset(conn, bundles=bundles, resolutions=[load_json(ARTIFACTS / "resolution" / "links.json")], catalog=catalog)

    validator = Draft202012Validator(load_json(CANONICAL_SCHEMA), format_checker=FormatChecker())
    results = []
    for kind, bundle, ref in TARGETS:
        canonical_id = next(
            item["canonical_id"]
            for item in catalog[f"canonical_{'entities' if kind == 'entity' else 'events'}"]
            if {"bundle": bundle, "ref": ref} in item["representations"]
        )
        with psycopg.connect(database_url) as conn:
            context = P.load_generation_context(conn, target_kind=kind, canonical_id=canonical_id)
        result = {
            "target_kind": kind,
            "canonical_id": canonical_id,
            "input_fingerprint": context["input_fingerprint"],
            "requires_uncertainty": context["constraints"]["requires_uncertainty"],
            "accepted": False,
        }
        model = RecordedModel(provider)
        phase = "generation"
        try:
            # No database connection is held across the production model call.
            candidate = P.generate_candidate(context, model)
            phase = "candidate_schema"
            validator.validate(json.loads(model.raw))
            phase = "persistence"
            with psycopg.connect(database_url) as conn:
                current = P.load_generation_context(conn, target_kind=kind, canonical_id=canonical_id)
                if current["input_fingerprint"] != context["input_fingerprint"]:
                    raise RuntimeError("presentation input changed")
                stored = P.persist_candidate(conn, context=current, candidate=candidate, model_version=model.name)
            with psycopg.connect(database_url) as conn:
                adopted = P.persist_candidate(conn, context=current, candidate=candidate, model_version=model.name)
            if not adopted["adopted"] or adopted["presentation_id"] != stored["presentation_id"]:
                raise RuntimeError("exact input/content did not adopt")
            result.update({
                "accepted": True,
                "blocks": len(candidate["blocks"]),
                "support_refs": sum(len(block["claim_refs"]) for block in candidate["blocks"]),
                "uncertainty_blocks": sum(block["block_kind"] == "uncertainty" for block in candidate["blocks"]),
                "content_sha256": stored["content_sha256"],
                "persisted_and_adopted": True,
            })
        except Exception as exc:
            # Validation exceptions may contain source/model text: do not echo
            # their messages or a traceback into shared workflow logs.
            result.update({"failure_phase": phase, "error_type": type(exc).__name__})
        result["raw_chars"] = len(model.raw)
        result["raw_response_sha256"] = hashlib.sha256(model.raw.encode("utf-8")).hexdigest() if model.raw else None
        results.append(result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return results


def main() -> int:
    if os.environ.get("CHRONICLE_MODEL_FIXTURE_PACK", "").strip():
        raise SystemExit("live presentation contract refuses fixture mode")
    control_url = os.environ.get("LOOM_TEST_POSTGRES_URL")
    if not control_url:
        raise SystemExit("LOOM_TEST_POSTGRES_URL is required for an isolated test database")
    _, provider = model_provider.models_from_env()
    if not isinstance(provider, model_provider.ResponsesHTTPModel):
        raise SystemExit("CHRONICLE_PRESENTATION_MODEL/live provider is required")
    database_name = f"chronicle_live_reader_{uuid.uuid4().hex}"
    params = conninfo_to_dict(control_url)
    params["dbname"] = database_name
    with psycopg.connect(control_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        results = verify(make_conninfo(**params), provider)
    finally:
        with psycopg.connect(control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name)))
    passed = len(results) == len(TARGETS) and all(item["accepted"] for item in results)
    print(json.dumps({
        "schema": "chronicle.live-presentation-contract",
        "prompt_version": P.PROMPT_VERSION,
        "model": provider.name,
        "accepted": passed,
        "target_count": len(results),
    }, sort_keys=True))
    print(f"Chronicle live presentation contract: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
