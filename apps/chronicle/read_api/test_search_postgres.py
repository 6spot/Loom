"""Chronicle C0-T12 lexical search tests against the retained PostgreSQL world."""

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

from migrations import apply_migrations
from postgres_v0 import persist_dataset
from repository import ChronicleReadRepository
from router import dispatch
from search import search_catalog
from test_postgres_v0 import _control_url, _database_conninfo
from test_read_model_postgres import _load_dataset, _membership


class ChronicleSearchRealDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundles, cls.resolutions, cls.catalog = _load_dataset()
        cls.entity_membership = _membership(cls.catalog, "canonical_entities")
        cls.event_membership = _membership(cls.catalog, "canonical_events")
        cls.control_url = _control_url()
        cls.database_name = f"chronicle_search_{uuid.uuid4().hex}"
        with psycopg.connect(cls.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.database_name)))
        cls.database_url = _database_conninfo(cls.control_url, cls.database_name)
        with psycopg.connect(cls.database_url) as conn:
            apply_migrations(conn)
            result = persist_dataset(
                conn,
                bundles=cls.bundles,
                resolutions=cls.resolutions,
                catalog=cls.catalog,
            )
            if result.totals["canonical_entities"] != 66 or result.totals["canonical_events"] != 45:
                raise AssertionError(f"unexpected real dataset totals: {result.totals}")

    @classmethod
    def tearDownClass(cls) -> None:
        with psycopg.connect(cls.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(cls.database_name)))

    def _search(self, q: str, *, kind: str = "all", limit: int = 20) -> dict:
        with psycopg.connect(self.database_url) as conn:
            conn.execute("BEGIN READ ONLY")
            return search_catalog(conn, q=q, kind=kind, limit=limit)

    def test_cao_cao_returns_one_canonical_entity_backed_by_both_sources(self) -> None:
        result = self._search("曹操", kind="entity")
        matches = [item for item in result["items"] if item["display"].get("name") == "曹操"]
        self.assertEqual(len(matches), 1)
        item = matches[0]
        self.assertEqual(item["match"]["rank"], 0)
        self.assertEqual(item["representation_count"], 2)
        self.assertEqual(item["source_count"], 2)
        self.assertEqual(item["navigation_path"], f"/entities/{item['canonical_id']}")
        self.assertEqual(
            {surface["bundle"] for surface in item["match"]["matched_surfaces"] if surface["bundle"]},
            {"wudi", "wuzhu"},
        )

    def test_red_cliffs_returns_one_canonical_event_not_two_representations(self) -> None:
        result = self._search("赤壁之战", kind="event")
        matches = [item for item in result["items"] if item["display"].get("title") == "赤壁之战"]
        self.assertEqual(len(matches), 1)
        item = matches[0]
        self.assertEqual(item["match"]["rank"], 0)
        self.assertEqual(item["representation_count"], 2)
        self.assertEqual(item["source_count"], 2)
        self.assertEqual(item["time"]["start_year"], 208)
        self.assertEqual(item["navigation_path"], f"/events/{item['canonical_id']}")

    def test_chibi_surfaces_event_and_distinct_uncertain_place_entities(self) -> None:
        result = self._search("赤壁", limit=20)
        event_titles = {
            item["display"].get("title")
            for item in result["items"]
            if item["kind"] == "event"
        }
        self.assertIn("赤壁之战", event_titles)
        place_items = [
            item
            for item in result["items"]
            if item["kind"] == "entity" and item["display"].get("name") == "赤壁"
        ]
        self.assertEqual(len(place_items), 2)
        self.assertEqual(len({item["canonical_id"] for item in place_items}), 2)
        self.assertTrue(all(item["identity_uncertain"] for item in place_items))

    def test_jiangling_keeps_related_events_as_separate_search_results(self) -> None:
        result = self._search("江陵", kind="event", limit=50)
        titles = {
            item["display"].get("title"): item["canonical_id"]
            for item in result["items"]
        }
        self.assertIn("曹操进军江陵", titles)
        self.assertIn("曹操北还并留军守江陵、襄阳", titles)
        self.assertNotEqual(titles["曹操进军江陵"], titles["曹操北还并留军守江陵、襄阳"])

    def test_alias_or_mention_surface_resolves_to_its_canonical_entity(self) -> None:
        candidate = None
        for label, bundle in sorted(self.bundles.items()):
            for entity in bundle["entities"]:
                canonical_name = entity["canonical_name"]
                for alias in entity.get("aliases") or []:
                    if alias and alias != canonical_name:
                        candidate = (label, entity, alias, "entity.alias")
                        break
                if candidate:
                    break
                for mention in entity.get("mentions") or []:
                    text = mention.get("text") if isinstance(mention, dict) else None
                    if text and text != canonical_name:
                        candidate = (label, entity, text, "entity.mention")
                        break
                if candidate:
                    break
            if candidate:
                break
        self.assertIsNotNone(candidate, "retained real data needs at least one alias/mention search surface")
        label, entity, query, field = candidate
        ref = entity.get("id") or entity.get("temp_id")
        canonical_id = self.entity_membership[(label, ref)]

        result = self._search(query, kind="entity", limit=50)
        item = next(item for item in result["items"] if item["canonical_id"] == canonical_id)
        self.assertTrue(any(surface["field"] == field for surface in item["match"]["matched_surfaces"]))

    def test_router_validates_search_contract(self) -> None:
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            repo = ChronicleReadRepository(conn)
            status, payload = dispatch(repo, "GET", "/v0/search", "q=%E6%9B%B9%E6%93%8D&kind=entity&limit=5")
            self.assertEqual(status, 200)
            self.assertEqual(payload["schema"], "chronicle.search")
            self.assertEqual(payload["query"]["q"], "曹操")

            status, payload = dispatch(repo, "GET", "/v0/search", "q=&kind=all")
            self.assertEqual(status, 400)
            self.assertEqual(payload["error"]["code"], "bad_request")

            status, payload = dispatch(repo, "GET", "/v0/search", "q=%E6%9B%B9%E6%93%8D&kind=semantic")
            self.assertEqual(status, 400)
            self.assertEqual(payload["error"]["code"], "bad_request")


if __name__ == "__main__":
    unittest.main()
