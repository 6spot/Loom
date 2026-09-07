"""R19 conflicts travel through the real Studio HTTP sidecar without writes."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import psycopg
from psycopg import sql

HERE = Path(__file__).resolve().parent
for path in (str(HERE), str(HERE.parent / "persistence")):
    if path not in sys.path:
        sys.path.insert(0, path)

import test_control_plane_postgres as pg
from server import handler_class
from studio_reviews import STUDIO_REVIEWS_PREFIX
from test_entity_review_conflict_r19_postgres import (
    CANONICAL_A, CANONICAL_B, INCOMING, R19_REFS, review_fixture, seed_reviews,
)


class StudioEntityConflictHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = pg._control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_r19_http_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        self.database_url = pg._database_conninfo(self.control_url, self.database_name)
        fixture = review_fixture(b_refs=(*R19_REFS, "ent_safe"))
        for label, bundle in fixture["bundles"].items():
            bundle["claims"] = [
                {
                    "temp_id": f"clm_{index:03}", "kind": "claim",
                    "subject": {"kind": "entity_ref", "ref": entity["temp_id"]},
                    "predicate": "described_as",
                    "object": {"kind": "literal", "value": "襄阳"},
                    "evidence": {
                        "source_ref": "src_001", "text": "軍次襄陽。",
                        "locator": {"work": "三国志", "chapter": label},
                    },
                }
                for index, entity in enumerate(bundle["entities"])
            ]
        with psycopg.connect(self.database_url) as conn:
            self.job, self.reviews = seed_reviews(conn, fixture)
        self.storage = tempfile.TemporaryDirectory(prefix="chronicle-r19-http-")
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), handler_class(self.database_url, storage_dir=self.storage.name),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=10)
        self.server.server_close()
        self.storage.cleanup()
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name)))

    def _request(self, canonical_id: str, decision: str | None = None, **extra):
        path = f"{STUDIO_REVIEWS_PREFIX}/{self.reviews[canonical_id]}"
        body = None
        if decision is not None:
            path += "/decision"
            body = json.dumps({
                "decision": decision, "rationale": "依据逐字来源证据", "confidence": 0.9, **extra,
            }).encode()
        request = Request(
            f"http://127.0.0.1:{self.server.server_port}{path}", data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def _snapshot(self):
        with psycopg.connect(self.database_url) as conn:
            return conn.execute("SELECT * FROM chronicle.review_items ORDER BY review_id").fetchall()

    def test_typed_409_has_readable_targets_exact_evidence_and_unchanged_history(self) -> None:
        self.assertEqual(self._request(CANONICAL_A, "same_entity")[0], 200)
        before = self._snapshot()
        status, response = self._request(CANONICAL_B, "same_entity")
        self.assertEqual(status, 409, response)
        self.assertEqual(response["schema"], "chronicle.error")
        error = response["error"]
        self.assertEqual(error["code"], "canonical_identity_conflict")
        self.assertIn("已经发布的实体", error["message"])
        details = error["details"]
        self.assertEqual(details["canonical_ids"], [CANONICAL_A, CANONICAL_B])
        self.assertEqual(
            [(target["canonical_id"], target["names"]) for target in details["canonical_entities"]],
            [(CANONICAL_A, ["襄阳"]), (CANONICAL_B, ["襄阳"])],
        )
        self.assertEqual(len(details["review_group_ids"]), 1)
        group = details["review_groups"][0]
        self.assertEqual(group["review_group_id"], details["review_group_ids"][0])
        self.assertEqual({context["ref"] for context in group["right_contexts"]}, set(R19_REFS))
        for context in group["right_contexts"]:
            self.assertEqual(context["bundle"], INCOMING)
            self.assertEqual(context["display"]["name"], "襄阳")
            self.assertEqual(context["display"]["evidence"][0]["text"], "軍次襄陽。")
        self.assertEqual(self._snapshot(), before)
        status, response = self._request(CANONICAL_B)
        self.assertEqual(status, 200)
        self.assertEqual(response["review"]["status"], "open")
        self.assertIsNone(response["review"]["decision"])
        self.assertEqual(response["review"]["job_open_resolution_reviews"], 1)
        self.assertEqual(self._request(CANONICAL_B, "not_same")[0], 200)

    def test_uncertain_default_same_override_conflicts_and_corrected_override_succeeds(self) -> None:
        self.assertEqual(self._request(CANONICAL_A, "same_entity")[0], 200)
        _, response = self._request(CANONICAL_B)
        group = next(
            group for group in response["review"]["review_groups"]
            if any(context["ref"] in R19_REFS for context in group["right_contexts"])
        )
        override = {
            "review_group_id": group["review_group_id"], "decision": "same_entity",
            "rationale": "此来源候选组有例外", "confidence": 0.8,
        }
        before = self._snapshot()
        status, response = self._request(CANONICAL_B, "uncertain", group_decisions=[override])
        self.assertEqual(status, 409, response)
        self.assertEqual(response["error"]["code"], "canonical_identity_conflict")
        self.assertEqual(response["error"]["details"]["review_group_ids"], [group["review_group_id"]])
        self.assertEqual(self._snapshot(), before)
        override["decision"] = "uncertain"
        status, response = self._request(CANONICAL_B, "same_entity", group_decisions=[override])
        self.assertEqual(status, 200, response)
        self.assertEqual(response["review"]["status"], "resolved")
        self.assertEqual(response["review"]["decision"]["group_decisions"], [override])


if __name__ == "__main__":
    unittest.main()
