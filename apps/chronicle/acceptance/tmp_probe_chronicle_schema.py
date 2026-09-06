#!/usr/bin/env python3
"""TEMP ONLY: test Chronicle canonical schema through Responses structured output."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib import request, error

ROOT = Path(__file__).resolve().parents[3]
schema_path = ROOT / "apps" / "chronicle" / "ingestion" / "schemas" / "chronicle-v0.1.schema.json"
schema = json.loads(schema_path.read_text(encoding="utf-8"))
endpoint = os.environ["CHRONICLE_MODEL_ENDPOINT"].strip()
api_key = os.environ["CHRONICLE_MODEL_API_KEY"].strip()
model = os.environ["CHRONICLE_EXTRACTION_MODEL"].strip()
timeout = float(os.environ.get("CHRONICLE_MODEL_TIMEOUT_SECONDS", "600"))

body = {
    "model": model,
    "input": (
        "Return one minimal Chronicle ingestion bundle for the exact source text 劉表卒. "
        "Use schema_version 0.1, source temp_id src_001, one person entity ent_001 named 劉表, "
        "one death event evt_001, one exact-evidence claim clm_001, and no canonical ids."
    ),
    "text": {
        "format": {
            "type": "json_schema",
            "name": "chronicle_bundle_probe",
            "schema": schema,
            "strict": True,
        }
    },
}
req = request.Request(
    endpoint,
    data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Loom-Chronicle-Schema-Probe/0.1",
    },
    method="POST",
)
try:
    with request.urlopen(req, timeout=timeout) as response:
        raw = response.read(2 * 1024 * 1024)
except error.HTTPError as exc:
    print(json.dumps({"canonical_schema_structured_supported": False, "http_status": exc.code}, sort_keys=True))
    raise SystemExit(2)

payload = json.loads(raw.decode("utf-8"))
text = payload.get("output_text")
if not isinstance(text, str):
    parts = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("type") == "output_text" and isinstance(part.get("text"), str):
                parts.append(part["text"])
    text = "".join(parts)
parsed = json.loads(text)
valid_shape = isinstance(parsed, dict) and parsed.get("schema_version") == "0.1" and all(
    key in parsed for key in ("source", "entities", "events", "claims", "warnings")
)
print(json.dumps({
    "canonical_schema_structured_supported": bool(valid_shape),
    "raw_chars": len(text),
    "raw_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    "top_level_keys": sorted(parsed.keys()) if isinstance(parsed, dict) else [],
}, sort_keys=True))
raise SystemExit(0 if valid_shape else 3)
