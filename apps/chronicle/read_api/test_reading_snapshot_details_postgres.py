"""PostgreSQL 18 tests for the C2-R2-T08 optional snapshot Event/Entity detail.

``continuous-reading.md`` §6 requires the existing ``/v0/events/{id}`` and
``/v0/entities/{id}`` details to accept an optional snapshot ``catalog`` that
restricts source representations, related objects and resolution/relation
provenance to the chosen snapshot's actual members, while the no-parameter
call keeps the original behavior. The fixtures reuse the real C0-T7 dataset
and persist *subset* catalogs over the same global representation tables, so a
later/other representation is globally resolvable but must stay invisible when
an older snapshot is requested.
"""

from __future__ import annotations

import copy
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

import canonical_store as _canonical_store
from common import load_json, record_ref
from migrations import apply_migrations
from postgres_v0 import persist_dataset
from test_postgres_v0 import _control_url, _database_conninfo
from read_common import ReadModelError, ReadModelNotFound
from repository import ChronicleReadRepository


ARTIFACT_ROOT = ROOT / "apps/chronicle/.artifacts/c0-t7"


def _load_dataset() -> tuple[dict[str, dict], list[dict], dict]:
    return (
        {
            "wudi": load_json(ARTIFACT_ROOT / "wudi/final.json"),
            "wuzhu": load_json(ARTIFACT_ROOT / "wuzhu/final.json"),
        },
        [load_json(ARTIFACT_ROOT / "resolution/links.json")],
        load_json(ARTIFACT_ROOT / "publication/catalog.json"),
    )


def _membership(catalog: dict, field: str) -> dict[tuple[str, str], str]:
    result = {}
    for record in catalog[field]:
        for representation in record["representations"]:
            result[(representation["bundle"], representation["ref"])] = record["canonical_id"]
    return result


def _find_ref(bundle: dict, collection: str, field: str, value: str) -> str:
    matches = [record_ref(record) for record in bundle[collection] if record.get(field) == value]
    if len(matches) != 1:
        raise AssertionError(f"expected one {collection} with {field}={value!r}, got {matches}")
    return matches[0]


def _event_id_for_title(
    membership: dict[tuple[str, str], str], bundles: dict, label: str, title: str
) -> str:
    ref = _find_ref(bundles[label], "events", "title", title)
    return membership[(label, ref)]


class ReadingSnapshotDetailsPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundles, cls.resolutions, cls.catalog = _load_dataset()
        cls.event_membership = _membership(cls.catalog, "canonical_events")
        cls.entity_membership = _membership(cls.catalog, "canonical_entities")
        cls.control_url = _control_url()
        cls.database_name = f"chronicle_t08_details_{uuid.uuid4().hex}"
        with psycopg.connect(cls.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.database_name)))
        cls.database_url = _database_conninfo(cls.control_url, cls.database_name)
        with psycopg.connect(cls.database_url) as conn:
            apply_migrations(conn)
            persist_dataset(
                conn,
                bundles=cls.bundles,
                resolutions=cls.resolutions,
                catalog=cls.catalog,
            )

            cls.red_cliffs_id = _event_id_for_title(
                cls.event_membership, cls.bundles, "wudi", "赤壁之战"
            )
            cls.wudi_ref = _find_ref(cls.bundles["wudi"], "events", "title", "赤壁之战")
            cls.wuzhu_ref = _find_ref(cls.bundles["wuzhu"], "events", "title", "赤壁之战")

            cls.cao_cao_id = cls.entity_membership[
                ("wudi", _find_ref(cls.bundles["wudi"], "entities", "canonical_name", "曹操"))
            ]
            cls.cao_wuzhu_ref = _find_ref(
                cls.bundles["wuzhu"], "entities", "canonical_name", "曹操"
            )

            # Snapshot that drops the wuzhu representation of the Red Cliffs
            # event: the representation is still globally resolvable but must
            # not appear in the scoped detail.
            subset = copy.deepcopy(cls.catalog)
            for record in subset["canonical_events"]:
                if record["canonical_id"] == cls.red_cliffs_id:
                    record["representations"] = [
                        rep for rep in record["representations"] if rep["bundle"] != "wuzhu"
                    ]
            cls.red_cliffs_wudi_only_sha, _ = _canonical_store.persist_catalog(conn, subset)

            # Snapshot that drops the wuzhu Cao Cao representation.
            subset = copy.deepcopy(cls.catalog)
            for record in subset["canonical_entities"]:
                if record["canonical_id"] == cls.cao_cao_id:
                    record["representations"] = [
                        rep for rep in record["representations"] if rep["bundle"] != "wuzhu"
                    ]
            cls.cao_wudi_only_sha, _ = _canonical_store.persist_catalog(conn, subset)

            # Snapshot that drops one of the two related Jiangling events.
            cls.jiangling_wudi_id = _event_id_for_title(
                cls.event_membership, cls.bundles, "wudi", "曹操进军江陵"
            )
            cls.jiangling_wuzhu_id = _event_id_for_title(
                cls.event_membership, cls.bundles, "wuzhu", "曹操北还并留军守江陵、襄阳"
            )
            subset = copy.deepcopy(cls.catalog)
            subset["canonical_events"] = [
                record
                for record in subset["canonical_events"]
                if record["canonical_id"] != cls.jiangling_wuzhu_id
            ]
            cls.jiangling_no_wuzhu_sha, _ = _canonical_store.persist_catalog(conn, subset)

            # Snapshot that keeps both related events and their representations
            # but omits *the relation itself*: the relation exists globally and
            # in the full catalog, but this earlier snapshot must not leak it.
            cls.full_catalog_sha, _ = _canonical_store.persist_catalog(conn, cls.catalog)
            pair = {cls.jiangling_wudi_id, cls.jiangling_wuzhu_id}
            subset = copy.deepcopy(cls.catalog)
            subset["event_relations"] = [
                relation
                for relation in subset["event_relations"]
                if {
                    relation.get("left_canonical_event_id"),
                    relation.get("right_canonical_event_id"),
                }
                != pair
            ]
            cls.jiangling_no_relation_sha, _ = _canonical_store.persist_catalog(conn, subset)

    @classmethod
    def tearDownClass(cls) -> None:
        with psycopg.connect(cls.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(cls.database_name))
            )

    def _repo(self):
        conn = psycopg.connect(self.database_url, autocommit=True)
        conn.execute("BEGIN READ ONLY")
        return conn, ChronicleReadRepository(conn)

    def test_event_detail_without_catalog_is_unchanged(self) -> None:
        conn, repo = self._repo()
        try:
            detail = repo.event_detail(self.red_cliffs_id)
            self.assertEqual(
                {item["bundle"] for item in detail["representations"]}, {"wudi", "wuzhu"}
            )
            self.assertEqual(detail["source_count"], 2)
            self.assertEqual(detail["representation_count"], 2)
        finally:
            conn.close()

    def test_event_detail_catalog_restricts_representations(self) -> None:
        conn, repo = self._repo()
        try:
            full = repo.event_detail(self.red_cliffs_id)
            scoped = repo.event_detail(
                self.red_cliffs_id, catalog_sha=self.red_cliffs_wudi_only_sha
            )
            self.assertEqual(
                {item["bundle"] for item in scoped["representations"]}, {"wudi"}
            )
            self.assertEqual(scoped["source_count"], 1)
            self.assertEqual(scoped["representation_count"], 1)
            self.assertLess(
                scoped["representation_count"], full["representation_count"]
            )
            # A resolution link that reaches an out-of-snapshot representation
            # must not leak into the scoped detail.
            for link in scoped["resolution_links"]:
                self.assertEqual(link["left"]["bundle"], "wudi")
                self.assertEqual(link["right"]["bundle"], "wudi")
        finally:
            conn.close()

    def test_event_detail_related_events_restricted_to_snapshot(self) -> None:
        conn, repo = self._repo()
        try:
            scoped = repo.event_detail(
                self.jiangling_wudi_id, catalog_sha=self.jiangling_no_wuzhu_sha
            )
            related_ids = {
                item["event"]["canonical_event_id"] for item in scoped["related_events"]
            }
            self.assertNotIn(self.jiangling_wuzhu_id, related_ids)
        finally:
            conn.close()

        conn, repo = self._repo()
        try:
            full = repo.event_detail(self.jiangling_wudi_id)
            related_ids = {
                item["event"]["canonical_event_id"] for item in full["related_events"]
            }
            self.assertIn(self.jiangling_wuzhu_id, related_ids)
        finally:
            conn.close()

    def test_relation_introduced_later_does_not_leak_into_old_snapshot(self) -> None:
        # Both endpoints stay in the snapshot, but the relation is only listed
        # by the full catalog. The earlier snapshot must not surface it.
        conn, repo = self._repo()
        try:
            leaked = repo.event_detail(
                self.jiangling_wudi_id, catalog_sha=self.jiangling_no_relation_sha
            )
            self.assertEqual(leaked["related_events"], [])
            leaked_ids = {
                item["event"]["canonical_event_id"] for item in leaked["related_events"]
            }
            self.assertNotIn(self.jiangling_wuzhu_id, leaked_ids)

            full = repo.event_detail(
                self.jiangling_wudi_id, catalog_sha=self.full_catalog_sha
            )
            full_ids = {
                item["event"]["canonical_event_id"] for item in full["related_events"]
            }
            self.assertIn(self.jiangling_wuzhu_id, full_ids)
        finally:
            conn.close()

    def test_entity_detail_catalog_restricts_representations(self) -> None:
        conn, repo = self._repo()
        try:
            full = repo.entity_detail(self.cao_cao_id)
            scoped = repo.entity_detail(self.cao_cao_id, catalog_sha=self.cao_wudi_only_sha)
            self.assertEqual(
                {item["bundle"] for item in scoped["representations"]}, {"wudi"}
            )
            self.assertLess(scoped["source_count"], full["source_count"])
        finally:
            conn.close()

    def test_unknown_catalog_is_not_found_and_bad_sha_is_bad_request(self) -> None:
        conn, repo = self._repo()
        try:
            with self.assertRaises(ReadModelNotFound):
                repo.event_detail(self.red_cliffs_id, catalog_sha="0" * 64)
            with self.assertRaises(ReadModelNotFound):
                repo.entity_detail(self.cao_cao_id, catalog_sha="0" * 64)
            with self.assertRaises(ReadModelError):
                repo.event_detail(self.red_cliffs_id, catalog_sha="not-a-sha")
        finally:
            conn.close()

    def test_event_not_in_snapshot_is_not_found(self) -> None:
        conn, repo = self._repo()
        try:
            # The dropped wuzhu Jiangling event is not a member of that snapshot.
            with self.assertRaises(ReadModelNotFound):
                repo.event_detail(
                    self.jiangling_wuzhu_id, catalog_sha=self.jiangling_no_wuzhu_sha
                )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
