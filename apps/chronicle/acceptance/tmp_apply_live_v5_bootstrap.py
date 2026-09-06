#!/usr/bin/env python3
"""TEMP ONLY: repair quoting in tmp_apply_live_v5.py and execute it."""

from pathlib import Path

path = Path(__file__).with_name("tmp_apply_live_v5.py")
text = path.read_text()
text = text.replace(
    "    tail = '''def _repair_snapshot(candidate: dict[str, Any]) -> dict[str, Any]:",
    '    tail = """def _repair_snapshot(candidate: dict[str, Any]) -> dict[str, Any]:',
    1,
)
text = text.replace(
    "---END CHUNK---\n'''\n'''\n    path.write_text(prefix + tail)",
    "---END CHUNK---\n'''\n\"\"\"\n    path.write_text(prefix + tail)",
    1,
)
code = compile(text, str(path), "exec")
namespace = {"__name__": "__main__", "__file__": str(path)}
exec(code, namespace)
