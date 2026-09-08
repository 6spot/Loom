"""Assemble C2-R1-T02 first-round upload inputs from pinned prepared sources.

Deterministic derivation (no network, no model):

* ``ingest/sanguozhi-three-chapters.md`` — one ``# 三國志`` book heading plus
  three ``##`` natural chapters whose bodies are byte-identical to the three
  reused Sanguozhi prepared ``.txt`` files.  A single file means a single
  Studio revision, so downstream cross-chapter checks run within one
  revision instead of three separate jobs.
* ``ingest/zizhi-tongjian-065.md`` — one ``# 資治通鑑`` book heading plus a
  single ``##`` chapter holding the complete pinned volume 65 text.

Embedding rule (also enforced by ``test_first_round_pack.py``): each chapter
body equals the prepared source text with trailing newlines rstripped, the
chapter block is ``## {title}\\n\\n{body}\\n``, and the file is
``# {book}\\n\\n`` + concatenated chapter blocks ending in exactly one
``\\n``.  ``ingest-manifest.json`` records every chapter's source
file/sha256/source range together with its ingest file/sha256/ingest range,
so any ``##`` chapter can be traced back to its exact download bytes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

FIRST_ROUND = Path(__file__).resolve().parent
SOURCES = FIRST_ROUND / "sources"
INGEST = FIRST_ROUND / "ingest"

BOOK_SANGUOZHI = "三國志"
CHAPTERS_SANGUOZHI: list[tuple[str, str, str]] = [
    ("xianzhu-liubei", "蜀書·先主傳", "sanguozhi-032-xianzhu-liubei.txt"),
    ("zhou-yu", "吳書·周瑜傳", "sanguozhi-054-zhou-yu.txt"),
    ("lu-su", "吳書·魯肅傳", "sanguozhi-054-lu-su.txt"),
]

BOOK_ZZTJ = "資治通鑑"
CHAPTERS_ZZTJ: list[tuple[str, str, str]] = [
    ("zztj-065", "卷第六十五 漢紀五十七（建安十一年至十三年）", "zizhi-tongjian-065-quan.txt"),
]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_markdown(book: str, chapters: list[tuple[str, str, str]]) -> tuple[str, list[dict]]:
    """Return (file_text, chapter_records) following the embedding rule."""
    text = f"# {book}\n\n"
    records: list[dict] = []
    for index, (key, title, filename) in enumerate(chapters):
        source_text = (SOURCES / filename).read_text(encoding="utf-8")
        body = source_text.rstrip("\n")
        heading = f"## {title}\n\n"
        start = len(text) + len(heading)
        end = start + len(body)
        text += heading + body + "\n"
        if index < len(chapters) - 1:
            text += "\n"
        records.append(
            {
                "key": key,
                "title": title,
                "source_file": f"sources/{filename}",
                "source_sha256": _sha256((SOURCES / filename).read_bytes()),
                "source_chars": len(source_text),
                "source_range": [0, len(body)],
                "ingest_range": [start, end],
            }
        )
    return text, records


def main() -> int:
    manifest = json.loads((FIRST_ROUND / "source-pack.json").read_text(encoding="utf-8"))
    prepared = json.loads((SOURCES / "prepared.json").read_text(encoding="utf-8"))
    prepared_by_key = {item["key"]: item for item in prepared["sources"]}

    INGEST.mkdir(parents=True, exist_ok=True)
    uploads: list[dict] = []

    for book, chapters, filename in (
        (BOOK_SANGUOZHI, CHAPTERS_SANGUOZHI, "sanguozhi-three-chapters.md"),
        (BOOK_ZZTJ, CHAPTERS_ZZTJ, "zizhi-tongjian-065.md"),
    ):
        text, records = build_markdown(book, chapters)
        target = INGEST / filename
        target.write_text(text, encoding="utf-8")
        file_sha = _sha256(target.read_bytes())
        for record in records:
            pinned = prepared_by_key[record["key"]]
            record["page_title"] = pinned["page_title"]
            record["oldid"] = pinned["oldid"]
            record["ingest_file"] = f"ingest/{filename}"
            record["ingest_sha256"] = file_sha
            record["ingest_chars"] = len(text)
        uploads.append(
            {
                "book": book,
                "ingest_file": f"ingest/{filename}",
                "sha256": file_sha,
                "chars": len(text),
                "bytes": len(text.encode("utf-8")),
                "chapters": records,
                "revision_note": (
                    "Single upload file forms a single Studio revision; all "
                    "chapters in this file share this ingest sha256 as their "
                    "revision locator, not separate jobs."
                ),
            }
        )

    ingest_manifest = {
        "schema": "chronicle.first-round-ingest-manifest",
        "version": "0.1",
        "pack_id": manifest["pack_id"],
        "prepared_manifest_sha256": prepared["manifest_sha256"],
        "embedding_rule": (
            "chapter body == prepared source text rstripped of trailing newlines; "
            "chapter block == '## {title}\\n\\n{body}\\n'; file == '# {book}\\n\\n' "
            "+ blocks joined by one blank line, ending in exactly one newline"
        ),
        "uploads": uploads,
    }
    (FIRST_ROUND / "ingest-manifest.json").write_text(
        json.dumps(ingest_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(ingest_manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
