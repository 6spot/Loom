#!/usr/bin/env python3
"""TEMP ONLY: probe structured JSON Schema output through configured Responses endpoint."""

from __future__ import annotations

import hashlib
import json
import os
from urllib import request, error

endpoint = os.environ["CHRONICLE_MODEL_ENDPOINT"].strip()
api_key = os.environ["CHRONICLE_MODEL_API_KEY"].strip()
model = os.environ["CHRONICLE_EXTRACTION_MODEL"].strip()
timeout = float(os.environ.get("CHRONICLE_MODEL_TIMEOUT_SECONDS", "600"))

schema = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "items"],
    "properties": {
        "schema_version": {"type": "string", "const": "probe-0.1"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "count"],
                "properties": {
                    "name": {"type": "string"},
                    "count": {"type": "integer"},
                },
            },
        },
    },
}
body = {
    "model": model,
    "input": "Return exactly two items: alpha count 1 and beta count 2.",
    "text": {
        "format": {
            "type": "json_schema",
            "name": "chronicle_structured_probe",
            "schema": schema,
            "strict": True,
        }
    },
}
req = request.Request(
    endpoint,
    data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Loom-Chronicle-Structured-Probe/0.1",
    },
    method="POST",
)
try:
    with request.urlopen(req, timeout=timeout) as response:
        raw = response.read(2 * 1024 * 1024)
except error.HTTPError as exc:
    print(json.dumps({"structured_output_supported": False, "http_status": exc.code}, sort_keys=True))
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
valid = (
    isinstance(parsed, dict)
    and parsed.get("schema_version") == "probe-0.1"
    and parsed.get("items") == [{"name": "alpha", "count": 1}, {"name": "beta", "count": 2}]
)
print(json.dumps({
    "structured_output_supported": bool(valid),
    "raw_chars": len(text),
    "raw_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    "top_level_keys": sorted(parsed.keys()) if isinstance(parsed, dict) else [],
}, sort_keys=True))
raise SystemExit(0 if valid else 3)
