"""Unit tests for T14 public chapter helpers (no database).

Covers versioned cursor round-trips and cross-scope replay rejection,
the explicit 8 MiB response cap, and method/route error mapping without
touching PostgreSQL. Database behavior lives in
``test_reader_chapters_postgres.py``.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PERSISTENCE = HERE.parent / "persistence"
for candidate in (str(HERE), str(PERSISTENCE)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import reader_chapters as chapters  # noqa: E402


class DirectoryCursorTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        cursor = chapters.encode_directory_cursor(
            document_id="019535d9-3df7-7000-8000-000000000001",
            revision_no=2,
            chapter_index=1,
            publication_id="019535d9-3df7-7001-8000-000000000001",
        )
        decoded = chapters.decode_directory_cursor(cursor)
        self.assertEqual("019535d9-3df7-7000-8000-000000000001", decoded["document_id"])
        self.assertEqual(2, decoded["revision_no"])
        self.assertEqual(1, decoded["chapter_index"])
        self.assertEqual(
            "019535d9-3df7-7001-8000-000000000001", decoded["publication_id"]
        )

    def test_tampered_and_foreign_cursors_rejected(self) -> None:
        with self.assertRaises(chapters._BadRequest):
            chapters.decode_directory_cursor("bogus!!")
        cursor = chapters.encode_directory_cursor(
            document_id="019535d9-3df7-7000-8000-000000000001",
            revision_no=1,
            chapter_index=0,
            publication_id="019535d9-3df7-7001-8000-000000000001",
        )
        tampered = cursor[:-2] + ("AA" if not cursor.endswith("AA") else "BB")
        with self.assertRaises(chapters._BadRequest):
            chapters.decode_directory_cursor(tampered)


class PublicSourceCursorTests(unittest.TestCase):
    def test_round_trip_chapter_relative_offset(self) -> None:
        cursor = chapters.encode_public_source_cursor(
            publication_id="019535d9-3df7-7001-8000-000000000001",
            anchor_id="anc_1",
            view="chapter",
            offset=16000,
        )
        self.assertEqual(
            16000,
            chapters.decode_public_source_cursor(
                cursor,
                publication_id="019535d9-3df7-7001-8000-000000000001",
                anchor_id="anc_1",
                view="chapter",
            ),
        )

    def test_cross_scope_replay_rejected(self) -> None:
        cursor = chapters.encode_public_source_cursor(
            publication_id="019535d9-3df7-7001-8000-000000000001",
            anchor_id="anc_1",
            view="chapter",
            offset=0,
        )
        for kwargs in (
            {
                "publication_id": "019535d9-3df7-7002-8000-000000000002",
                "anchor_id": "anc_1",
                "view": "chapter",
            },
            {
                "publication_id": "019535d9-3df7-7001-8000-000000000001",
                "anchor_id": "anc_2",
                "view": "chapter",
            },
            {
                "publication_id": "019535d9-3df7-7001-8000-000000000001",
                "anchor_id": "anc_1",
                "view": "window",
            },
        ):
            with self.assertRaises(chapters._BadRequest):
                chapters.decode_public_source_cursor(cursor, **kwargs)
        with self.assertRaises(chapters._BadRequest):
            chapters.decode_public_source_cursor(
                "bogus",
                publication_id="019535d9-3df7-7001-8000-000000000001",
                anchor_id="anc_1",
                view="chapter",
            )


class ResponseCapTests(unittest.TestCase):
    def test_small_payload_passes(self) -> None:
        raw = chapters.check_response_size({"items": []})
        self.assertTrue(raw.endswith(b"\n"))

    def test_oversized_full_text_fails_explicitly(self) -> None:
        payload = {"translation_blocks": [{"text": "x" * (9 * 1024 * 1024)}]}
        with self.assertRaises(chapters._Conflict) as ctx:
            chapters.check_response_size(payload)
        self.assertEqual("response_too_large", ctx.exception.code)


class DispatchErrorTests(unittest.TestCase):
    def test_wrong_method_is_405_without_db(self) -> None:
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            status, payload = chapters.dispatch_chapters(
                None, method=method, path="/v0/chapters", raw_query=""
            )
            self.assertEqual(405, status)
            self.assertEqual("method_not_allowed", payload["error"]["code"])

    def test_unknown_subroute_is_404_without_db(self) -> None:
        status, payload = chapters.dispatch_chapters(
            None, method="GET", path="/v0/chapters/a/b/c/d", raw_query=""
        )
        self.assertEqual(404, status)
        self.assertEqual("not_found", payload["error"]["code"])


if __name__ == "__main__":
    unittest.main()
