"""PostgreSQL/API integration for C1-T12 Reader Presentation."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PERSISTENCE = HERE.parent / "persistence"
for candidate in (str(HERE), str(PERSISTENCE)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import presentation  # noqa: E402
from repository import ChronicleReadRepository  # noqa: E402
from router import dispatch  # noqa: E402

DEFAULT_CONTROL_URL = "postgresql://loom:loom@127.0.0.1:15432/loom_control"


def _control_url() -> str:
    explicit = os.environ.get("LOOM_TEST_POSTGRES_URL")
    url = explicit or DEFAULT_CONTROL_URL
    try:
        with psycopg.connect(url, connect_timeout=2):
            return url
    except psycopg.Error:
        if explicit:
            raise
    subprocess.run(
        ["bash", "tools/postgres-test.sh", "up"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return url


def _database_conninfo(control_url: str, database_name: str) -> str:
    params = conninfo_to_dict(control_url)
    params["dbname"] = database_name
    return make_conninfo(**params)


class ReaderPresentationReadApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_read_t12_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        self.database_url = _database_conninfo(self.control_url, self.database_name)
        subprocess.run(
            [
                sys.executable,
                "apps/chronicle/persistence/chronicle_persist.py",
                "--database-url",
                self.database_url,
                "--bundle",
                "wudi=apps/chronicle/.artifacts/c0-t7/wudi/final.json",
                "--bundle",
                "wuzhu=apps/chronicle/.artifacts/c0-t7/wuzhu/final.json",
                "--resolution",
                "apps/chronicle/.artifacts/c0-t7/resolution/links.json",
                "--catalog",
                "apps/chronicle/.artifacts/c0-t7/publication/catalog.json",
            ],
            cwd=ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
        )

    def tearDown(self) -> None:
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name))
            )

    def _target_with_claim(self, conn, target_kind: str) -> str:
        if target_kind == "event":
            row = conn.execute(
                """
                SELECT DISTINCT r.canonical_id::text
                FROM chronicle.canonical_event_representations r
                JOIN chronicle.staged_claims c ON c.bundle_label = r.bundle_label
                WHERE (c.payload->'subject'->>'kind' = 'event_ref'
                       AND c.payload->'subject'->>'ref' = r.record_ref)
                   OR (c.payload->'object'->>'kind' = 'event_ref'
                       AND c.payload->'object'->>'ref' = r.record_ref)
                ORDER BY r.canonical_id::text
                LIMIT 1
                """
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT DISTINCT r.canonical_id::text
                FROM chronicle.canonical_entity_representations r
                JOIN chronicle.staged_claims c ON c.bundle_label = r.bundle_label
                WHERE (c.payload->'subject'->>'kind' = 'entity_ref'
                       AND c.payload->'subject'->>'ref' = r.record_ref)
                   OR (c.payload->'object'->>'kind' = 'entity_ref'
                       AND c.payload->'object'->>'ref' = r.record_ref)
                ORDER BY r.canonical_id::text
                LIMIT 1
                """
            ).fetchone()
        self.assertIsNotNone(row)
        return row[0]

    def test_event_and_entity_detail_expose_latest_grounded_projection(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            for target_kind in ("event", "entity"):
                canonical_id = self._target_with_claim(conn, target_kind)
                context = presentation.load_generation_context(
                    conn, target_kind=target_kind, canonical_id=canonical_id
                )
                claim = next(
                    claim
                    for rep in context["representations"]
                    for claim in rep["claims"]
                )
                block_kind = "overview" if target_kind == "entity" else "sequence"
                blocks = [
                    {
                        "block_kind": block_kind,
                        "epistemic_mode": "fact_summary",
                        "text": "这是一段只用于验证 Reader Presentation 读取链路的现代中文。",
                        "claim_refs": [
                            {"bundle": claim["bundle"], "ref": claim["ref"]}
                        ],
                    }
                ]
                if context["constraints"]["requires_uncertainty"]:
                    blocks.append(
                        {
                            "block_kind": "uncertainty",
                            "epistemic_mode": "uncertainty",
                            "text": "现有来源或身份解析仍保留不确定性，本段不把它消除。",
                            "claim_refs": [
                                {"bundle": claim["bundle"], "ref": claim["ref"]}
                            ],
                        }
                    )
                candidate = presentation.validate_candidate(
                    {
                        "schema": "chronicle.reader-presentation",
                        "version": "0.1",
                        "target_kind": target_kind,
                        "canonical_id": canonical_id,
                        "language": "zh-CN",
                        "blocks": blocks,
                    },
                    context,
                )
                stored = presentation.persist_candidate(
                    conn,
                    context=context,
                    candidate=candidate,
                    model_version="api-projection-test-v1",
                )
                conn.commit()

                repo = ChronicleReadRepository(conn)
                path = f"/v0/{'events' if target_kind == 'event' else 'entities'}/{canonical_id}"
                status, payload = dispatch(repo, "GET", path)
                self.assertEqual(status, 200)
                reader = payload["reader_presentation"]
                self.assertEqual(reader["presentation_id"], stored["presentation_id"])
                self.assertEqual(reader["language"], "zh-CN")
                self.assertEqual(reader["presentation_version"], 1)
                self.assertEqual(reader["blocks"][0]["text"], candidate["blocks"][0]["text"])
                support = reader["blocks"][0]["supports"][0]
                self.assertEqual((support["bundle"], support["ref"]), (claim["bundle"], claim["ref"]))
                self.assertTrue(support["claim"]["evidence"]["text"])
                self.assertTrue(support["claim"]["evidence"]["source_ref"])
                self.assertTrue(support["source"]["title"])

    def test_detail_returns_null_instead_of_request_time_generation(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            canonical_id = self._target_with_claim(conn, "event")
            repo = ChronicleReadRepository(conn)
            status, payload = dispatch(repo, "GET", f"/v0/events/{canonical_id}")
            self.assertEqual(status, 200)
            self.assertIsNone(payload["reader_presentation"])


if __name__ == "__main__":
    unittest.main()
