"""PostgreSQL 18 integration tests for Chronicle persistence v0."""

from __future__ import annotations

import copy
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
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from common import PersistenceConflict
from migrations import apply_migrations, migration_files
from postgres_v0 import persist_dataset


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
    with psycopg.connect(url, connect_timeout=10):
        return url


def _database_conninfo(control_url: str, database_name: str) -> str:
    params = conninfo_to_dict(control_url)
    params["dbname"] = database_name
    return make_conninfo(**params)


def _uuid7(n: int) -> str:
    # Deterministic RFC 9562 variant/version values for test fixtures.
    return f"019535d9-3df7-7{n:03x}-8000-00000000000{n:x}"


def _bundle(title: str, entity_name: str, event_title: str, evidence: str) -> dict:
    return {
        "schema_version": "0.1",
        "source": {
            "temp_id": "src_001",
            "kind": "source",
            "source_type": "book",
            "title": title,
            "language": "zh-Hant",
            "extraction": {"method": "model"},
        },
        "entities": [
            {
                "temp_id": "ent_001",
                "kind": "entity",
                "type": "person",
                "canonical_name": entity_name,
                "aliases": [],
                "mentions": [{"text": entity_name}],
                "resolution": {"status": "unresolved"},
                "extraction": {"method": "model"},
            }
        ],
        "events": [
            {
                "temp_id": "evt_001",
                "kind": "event",
                "type": "military",
                "title": event_title,
                "time": None,
                "participants": [{"entity_ref": "ent_001", "role": "actor"}],
                "places": [],
                "extraction": {"method": "model"},
            }
        ],
        "claims": [
            {
                "temp_id": "clm_001",
                "kind": "claim",
                "subject": {"kind": "entity_ref", "ref": "ent_001"},
                "predicate": "participated_in",
                "object": {"kind": "event_ref", "ref": "evt_001"},
                "time": None,
                "evidence": {
                    "text": evidence,
                    "source_ref": "src_001",
                    "locator": {"section": title},
                },
                "assessment": {"status": "unassessed"},
                "extraction": {"method": "model"},
            }
        ],
        "warnings": [],
    }


def _fixture() -> tuple[dict[str, dict], list[dict], dict]:
    bundles = {
        "left": _bundle("Left Source", "曹操", "曹操进军江陵", "left evidence"),
        "right": _bundle("Right Source", "曹操", "曹操北还并留军守江陵、襄阳", "right evidence"),
    }
    resolution = {
        "schema": "chronicle.resolution-links",
        "version": "0.1",
        "left_bundle": {"label": "left", "source_ref": "src_001", "source_title": "Left Source"},
        "right_bundle": {"label": "right", "source_ref": "src_001", "source_title": "Right Source"},
        "entity_links": [
            {
                "candidate_id": "ec_001",
                "left": {"bundle": "left", "ref": "ent_001"},
                "right": {"bundle": "right", "ref": "ent_001"},
                "decision": "same_entity",
                "confidence": 1.0,
                "rationale": "same person",
                "signals": ["name"],
            }
        ],
        "event_links": [
            {
                "candidate_id": "vc_001",
                "left": {"bundle": "left", "ref": "evt_001"},
                "right": {"bundle": "right", "ref": "evt_001"},
                "decision": "related_occurrence",
                "confidence": 0.9,
                "rationale": "related but distinct",
                "signals": ["participant"],
            }
        ],
        "warnings": [{"type": "review", "message": "kept distinct"}],
    }
    entity_id = _uuid7(1)
    left_event_id = _uuid7(2)
    right_event_id = _uuid7(3)
    catalog = {
        "schema": "chronicle.canonical-catalog",
        "version": "0.1",
        "canonical_entities": [
            {
                "canonical_id": entity_id,
                "representations": [
                    {"bundle": "left", "ref": "ent_001"},
                    {"bundle": "right", "ref": "ent_001"},
                ],
            }
        ],
        "canonical_events": [
            {
                "canonical_id": left_event_id,
                "representations": [{"bundle": "left", "ref": "evt_001"}],
            },
            {
                "canonical_id": right_event_id,
                "representations": [{"bundle": "right", "ref": "evt_001"}],
            },
        ],
        "event_relations": [
            {
                "type": "related_occurrence",
                "left_canonical_event_id": left_event_id,
                "right_canonical_event_id": right_event_id,
                "resolution_links": [
                    {
                        "candidate_id": "vc_001",
                        "left": {"bundle": "left", "ref": "evt_001"},
                        "right": {"bundle": "right", "ref": "evt_001"},
                    }
                ],
            }
        ],
        "warnings": [],
    }
    return bundles, [resolution], catalog


class ChroniclePostgresV0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_test_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        self.database_url = _database_conninfo(self.control_url, self.database_name)

    def tearDown(self) -> None:
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name))
            )

    def _connect_ready(self):
        conn = psycopg.connect(self.database_url)
        apply_migrations(conn)
        return conn

    def test_import_is_idempotent_and_restart_safe(self) -> None:
        bundles, resolutions, catalog = _fixture()
        with self._connect_ready() as conn:
            first = persist_dataset(conn, bundles=bundles, resolutions=resolutions, catalog=catalog)
            second = persist_dataset(conn, bundles=bundles, resolutions=resolutions, catalog=catalog)
            self.assertTrue(first.import_created)
            self.assertFalse(second.import_created)
            self.assertEqual(first.import_key, second.import_key)
            self.assertEqual(second.totals["canonical_entities"], 1)
            self.assertEqual(second.totals["canonical_events"], 2)
            self.assertEqual(second.totals["canonical_event_relations"], 1)
            self.assertEqual(second.totals["import_sets"], 1)

        with psycopg.connect(self.database_url) as conn:
            entity_ids = conn.execute(
                """
                SELECT canonical_id::text
                FROM chronicle.canonical_entity_representations
                ORDER BY bundle_label
                """
            ).fetchall()
            self.assertEqual(entity_ids, [(catalog["canonical_entities"][0]["canonical_id"],)] * 2)
            event_ids = conn.execute(
                """
                SELECT bundle_label, canonical_id::text
                FROM chronicle.canonical_event_representations
                ORDER BY bundle_label
                """
            ).fetchall()
            self.assertNotEqual(event_ids[0][1], event_ids[1][1])
            relation_count = conn.execute(
                "SELECT count(*) FROM chronicle.canonical_event_relations"
            ).fetchone()[0]
            provenance_count = conn.execute(
                "SELECT count(*) FROM chronicle.canonical_event_relation_links"
            ).fetchone()[0]
            self.assertEqual(relation_count, 1)
            self.assertEqual(provenance_count, 1)
            evidence = conn.execute(
                """
                SELECT payload->'evidence'->>'text'
                FROM chronicle.staged_claims
                WHERE bundle_label = 'left' AND record_ref = 'clm_001'
                """
            ).fetchone()[0]
            self.assertEqual(evidence, "left evidence")

    def test_conflicting_bundle_rewrite_rolls_back(self) -> None:
        bundles, resolutions, catalog = _fixture()
        with self._connect_ready() as conn:
            persist_dataset(conn, bundles=bundles, resolutions=resolutions, catalog=catalog)
            changed = copy.deepcopy(bundles)
            changed["left"]["source"]["title"] = "Changed Source"
            with self.assertRaises(PersistenceConflict):
                persist_dataset(conn, bundles=changed, resolutions=resolutions, catalog=catalog)
            title = conn.execute(
                "SELECT source_title FROM chronicle.source_bundles WHERE bundle_label = 'left'"
            ).fetchone()[0]
            imports = conn.execute("SELECT count(*) FROM chronicle.import_sets").fetchone()[0]
            self.assertEqual(title, "Left Source")
            self.assertEqual(imports, 1)

    def test_canonical_membership_reassignment_rolls_back(self) -> None:
        bundles, resolutions, catalog = _fixture()
        with self._connect_ready() as conn:
            persist_dataset(conn, bundles=bundles, resolutions=resolutions, catalog=catalog)
            changed = copy.deepcopy(catalog)
            changed["canonical_entities"][0]["canonical_id"] = _uuid7(9)
            with self.assertRaises(PersistenceConflict):
                persist_dataset(conn, bundles=bundles, resolutions=resolutions, catalog=changed)
            catalogs = conn.execute("SELECT count(*) FROM chronicle.canonical_catalogs").fetchone()[0]
            entities = conn.execute("SELECT count(*) FROM chronicle.canonical_entities").fetchone()[0]
            self.assertEqual(catalogs, 1)
            self.assertEqual(entities, 1)

    def test_migration_checksum_drift_fails(self) -> None:
        migration = migration_files()[0]
        with psycopg.connect(self.database_url) as conn:
            with conn.transaction():
                conn.execute("CREATE SCHEMA chronicle")
                conn.execute(
                    """
                    CREATE TABLE chronicle.schema_migrations (
                        version text PRIMARY KEY,
                        checksum text NOT NULL,
                        applied_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO chronicle.schema_migrations(version, checksum) VALUES (%s, %s)",
                    (migration.name, "0" * 64),
                )
            with self.assertRaises(PersistenceConflict):
                apply_migrations(conn)


if __name__ == "__main__":
    unittest.main()
