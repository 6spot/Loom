"""C1-T14 Coverage contracts against real C0 PostgreSQL data."""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg import sql

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PERSISTENCE = ROOT / "apps/chronicle/persistence"
for path in (PERSISTENCE, HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from common import load_json
from coverage import build_coverage
from migrations import apply_migrations
from postgres_v0 import persist_dataset
from repository import ChronicleReadRepository
from router import dispatch
from test_postgres_v0 import _control_url, _database_conninfo


ARTIFACT_ROOT = ROOT / "apps/chronicle/.artifacts/c0-t7"


class CoveragePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()
        cls.database_name = f"chronicle_coverage_{uuid.uuid4().hex}"
        with psycopg.connect(cls.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.database_name)))
        cls.database_url = _database_conninfo(cls.control_url, cls.database_name)
        bundles = {
            "wudi": load_json(ARTIFACT_ROOT / "wudi/final.json"),
            "wuzhu": load_json(ARTIFACT_ROOT / "wuzhu/final.json"),
        }
        resolutions = [load_json(ARTIFACT_ROOT / "resolution/links.json")]
        catalog = load_json(ARTIFACT_ROOT / "publication/catalog.json")
        with psycopg.connect(cls.database_url) as conn:
            apply_migrations(conn)
            persist_dataset(conn, bundles=bundles, resolutions=resolutions, catalog=catalog)

    @classmethod
    def tearDownClass(cls) -> None:
        with psycopg.connect(cls.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(cls.database_name))
            )

    def _coverage(self, **kwargs):
        with psycopg.connect(self.database_url) as conn:
            with conn.transaction():
                conn.execute("SET TRANSACTION READ ONLY")
                return build_coverage(conn, **kwargs)

    def test_real_corpus_projection_is_deterministic_and_non_authoritative(self) -> None:
        first = self._coverage()
        second = self._coverage()
        self.assertEqual(first, second)
        self.assertEqual(first["schema"], "chronicle.coverage")
        self.assertEqual(first["version"], "0.1")
        self.assertEqual(first["authority"]["kind"], "derived_projection")
        self.assertFalse(first["authority"]["historical_truth"])
        self.assertFalse(first["authority"]["mutates_history"])
        self.assertIn("not evidence", first["authority"]["absence_semantics"])
        self.assertEqual(first["catalog"]["published_source_bundle_count"], 2)
        self.assertEqual(first["entities"]["canonical_count"], 66)
        self.assertEqual(first["events"]["canonical_count"], 45)
        self.assertEqual(first["claims"]["published_source_claim_count"], 50)
        self.assertEqual(len(first["sources"]), 2)
        self.assertTrue(first["domains"]["event_types"])
        self.assertTrue(first["domains"]["claim_predicates"])
        self.assertEqual(first["presentations"]["entity_targets"], 66)
        self.assertEqual(first["presentations"]["event_targets"], 45)
        self.assertEqual(first["presentations"]["published_entity_targets"], 0)
        self.assertEqual(first["presentations"]["published_event_targets"], 0)

    def test_observed_years_and_explicit_unrepresented_year_never_claim_absence(self) -> None:
        year_208 = self._coverage(from_year=208, to_year=208)
        self.assertEqual(year_208["time"]["requested_year_count"], 1)
        self.assertGreater(year_208["time"]["years"][0]["event_count"], 0)
        self.assertGreater(year_208["events"]["scoped_canonical_count"], 0)

        outside = self._coverage(from_year=9999, to_year=9999)
        self.assertEqual(outside["time"]["years"], [{
            "year": 9999,
            "event_count": 0,
            "source_count": 0,
            "density": "unrepresented",
            "event_types": [],
        }])
        self.assertEqual(outside["events"]["scoped_canonical_count"], 0)
        self.assertIn("current corpus", outside["authority"]["absence_semantics"])
        self.assertIn("not evidence", outside["authority"]["absence_semantics"])

    def test_staged_inflight_bundle_does_not_change_published_coverage(self) -> None:
        before = self._coverage()
        with psycopg.connect(self.database_url) as conn:
            conn.execute(
                """
                INSERT INTO chronicle.source_bundles(
                    bundle_label, schema_version, source_ref, source_title,
                    artifact_sha256, source_payload, bundle_payload
                ) VALUES (%s, '0.1', 'src_inflight', 'in-flight source', %s, '{}'::jsonb, '{}'::jsonb)
                """,
                ("coverage-inflight", "a" * 64),
            )
            conn.execute(
                """
                INSERT INTO chronicle.staged_events(bundle_label, record_ref, payload_sha256, payload)
                VALUES (%s, 'evt_inflight', %s, %s::jsonb)
                """,
                (
                    "coverage-inflight",
                    "b" * 64,
                    '{"id":"evt_inflight","type":"invented-test-surface","title":"not published",'
                    '"time":{"normalized":{"year":9999}}}',
                ),
            )
            conn.commit()
        after = self._coverage()
        self.assertEqual(before, after)

    def test_router_validates_public_coverage_contract(self) -> None:
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            repo = ChronicleReadRepository(conn)
            status, payload = dispatch(repo, "GET", "/v0/coverage", "from_year=208&to_year=208")
            self.assertEqual(status, 200)
            self.assertEqual(payload["query"], {"from_year": 208, "to_year": 208})

            status, payload = dispatch(repo, "GET", "/v0/coverage", "from_year=210&to_year=208")
            self.assertEqual(status, 400)
            self.assertEqual(payload["error"]["code"], "bad_request")

            status, payload = dispatch(repo, "GET", "/v0/coverage", "completeness=true")
            self.assertEqual(status, 400)
            self.assertEqual(payload["error"]["code"], "bad_request")


if __name__ == "__main__":
    unittest.main()
