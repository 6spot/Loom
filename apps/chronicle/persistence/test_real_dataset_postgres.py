"""PostgreSQL 18 integration test over the retained Chronicle C0-T7 acceptance dataset."""

from __future__ import annotations

import sys
import unittest
import uuid
from collections import Counter
from pathlib import Path

import psycopg
from psycopg import sql

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from common import load_json, record_ref
from migrations import apply_migrations
from postgres_v0 import persist_dataset
from test_postgres_v0 import _control_url, _database_conninfo


ARTIFACT_ROOT = ROOT / "apps/chronicle/.artifacts/c0-t7"


def _load_real_dataset() -> tuple[dict[str, dict], list[dict], dict]:
    bundles = {
        "wudi": load_json(ARTIFACT_ROOT / "wudi/final.json"),
        "wuzhu": load_json(ARTIFACT_ROOT / "wuzhu/final.json"),
    }
    resolutions = [load_json(ARTIFACT_ROOT / "resolution/links.json")]
    catalog = load_json(ARTIFACT_ROOT / "publication/catalog.json")
    return bundles, resolutions, catalog


def _catalog_membership(catalog: dict, field: str) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for record in catalog[field]:
        canonical_id = record["canonical_id"]
        for representation in record["representations"]:
            result[(representation["bundle"], representation["ref"])] = canonical_id
    return result


class ChronicleRealDatasetPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_real_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        self.database_url = _database_conninfo(self.control_url, self.database_name)

    def tearDown(self) -> None:
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name))
            )

    def test_real_wudi_wuzhu_dataset_round_trip(self) -> None:
        bundles, resolutions, catalog = _load_real_dataset()
        resolution = resolutions[0]

        self.assertEqual(
            Counter(link["decision"] for link in resolution["entity_links"]),
            Counter({"same_entity": 5, "uncertain": 5}),
        )
        self.assertEqual(
            Counter(link["decision"] for link in resolution["event_links"]),
            Counter({"same_occurrence": 8, "related_occurrence": 2}),
        )
        self.assertEqual(len(catalog["canonical_entities"]), 66)
        self.assertEqual(len(catalog["canonical_events"]), 45)
        self.assertEqual(len(catalog["event_relations"]), 2)

        with psycopg.connect(self.database_url) as conn:
            apply_migrations(conn)
            first = persist_dataset(
                conn,
                bundles=bundles,
                resolutions=resolutions,
                catalog=catalog,
            )
            second = persist_dataset(
                conn,
                bundles=bundles,
                resolutions=resolutions,
                catalog=catalog,
            )

            self.assertTrue(first.import_created)
            self.assertFalse(second.import_created)
            self.assertEqual(first.import_key, second.import_key)
            self.assertEqual(second.totals["source_bundles"], 2)
            self.assertEqual(second.totals["canonical_entities"], 66)
            self.assertEqual(second.totals["canonical_events"], 45)
            self.assertEqual(second.totals["canonical_event_relations"], 2)
            self.assertEqual(second.totals["resolution_entity_links"], 10)
            self.assertEqual(second.totals["resolution_event_links"], 10)
            self.assertEqual(second.totals["import_sets"], 1)

        expected_entities = _catalog_membership(catalog, "canonical_entities")
        expected_events = _catalog_membership(catalog, "canonical_events")

        # Reconnect to prove persisted identity survives connection/process boundaries.
        with psycopg.connect(self.database_url) as conn:
            actual_entities = {
                (bundle, ref): canonical_id
                for bundle, ref, canonical_id in conn.execute(
                    """
                    SELECT bundle_label, record_ref, canonical_id::text
                    FROM chronicle.canonical_entity_representations
                    """
                ).fetchall()
            }
            actual_events = {
                (bundle, ref): canonical_id
                for bundle, ref, canonical_id in conn.execute(
                    """
                    SELECT bundle_label, record_ref, canonical_id::text
                    FROM chronicle.canonical_event_representations
                    """
                ).fetchall()
            }
            self.assertEqual(actual_entities, expected_entities)
            self.assertEqual(actual_events, expected_events)

            cao_cao = conn.execute(
                """
                SELECT r.bundle_label, r.record_ref, r.canonical_id::text
                FROM chronicle.canonical_entity_representations r
                JOIN chronicle.staged_entities s
                  ON s.bundle_label = r.bundle_label AND s.record_ref = r.record_ref
                WHERE s.payload->>'canonical_name' = '曹操'
                ORDER BY r.bundle_label
                """
            ).fetchall()
            self.assertEqual(len(cao_cao), 2)
            self.assertEqual(len({row[2] for row in cao_cao}), 1)

            chibi = conn.execute(
                """
                SELECT r.bundle_label, r.record_ref, r.canonical_id::text
                FROM chronicle.canonical_event_representations r
                JOIN chronicle.staged_events s
                  ON s.bundle_label = r.bundle_label AND s.record_ref = r.record_ref
                WHERE s.payload->>'title' = '赤壁之战'
                ORDER BY r.bundle_label
                """
            ).fetchall()
            self.assertEqual(len(chibi), 2)
            self.assertEqual(len({row[2] for row in chibi}), 1)

            for place_name in ("襄阳", "夏口", "江陵", "赤壁", "合肥"):
                rows = conn.execute(
                    """
                    SELECT r.bundle_label, r.record_ref, r.canonical_id::text
                    FROM chronicle.canonical_entity_representations r
                    JOIN chronicle.staged_entities s
                      ON s.bundle_label = r.bundle_label AND s.record_ref = r.record_ref
                    WHERE s.payload->>'canonical_name' = %s
                    ORDER BY r.bundle_label
                    """,
                    (place_name,),
                ).fetchall()
                self.assertEqual(len(rows), 2, place_name)
                self.assertEqual(len({row[2] for row in rows}), 2, place_name)

            jiangling_ids = {}
            for title in ("曹操进军江陵", "曹操北还并留军守江陵、襄阳"):
                row = conn.execute(
                    """
                    SELECT r.canonical_id::text
                    FROM chronicle.canonical_event_representations r
                    JOIN chronicle.staged_events s
                      ON s.bundle_label = r.bundle_label AND s.record_ref = r.record_ref
                    WHERE s.payload->>'title' = %s
                    """,
                    (title,),
                ).fetchone()
                self.assertIsNotNone(row, title)
                jiangling_ids[title] = row[0]

            left_id = jiangling_ids["曹操进军江陵"]
            right_id = jiangling_ids["曹操北还并留军守江陵、襄阳"]
            self.assertNotEqual(left_id, right_id)
            relation_rows = conn.execute(
                """
                SELECT relation_sha256
                FROM chronicle.canonical_event_relations
                WHERE relation_type = 'related_occurrence'
                  AND (
                    (left_canonical_event_id = %s::uuid AND right_canonical_event_id = %s::uuid)
                    OR
                    (left_canonical_event_id = %s::uuid AND right_canonical_event_id = %s::uuid)
                  )
                """,
                (left_id, right_id, right_id, left_id),
            ).fetchall()
            self.assertEqual(len(relation_rows), 1)

            expected_claims = {}
            for label, bundle in bundles.items():
                for claim in bundle["claims"]:
                    expected_claims[(label, record_ref(claim))] = claim
            actual_claims = {
                (label, ref): payload
                for label, ref, payload in conn.execute(
                    """
                    SELECT bundle_label, record_ref, payload
                    FROM chronicle.staged_claims
                    """
                ).fetchall()
            }
            self.assertEqual(actual_claims, expected_claims)

            provenance_count = conn.execute(
                "SELECT count(*) FROM chronicle.canonical_event_relation_links"
            ).fetchone()[0]
            self.assertEqual(provenance_count, 2)


if __name__ == "__main__":
    unittest.main()
