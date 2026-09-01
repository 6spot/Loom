"""Real Chronicle C0-T10 read-model tests against PostgreSQL 18."""

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

from common import load_json, record_ref
from migrations import apply_migrations
from postgres_v0 import persist_dataset
from test_postgres_v0 import _control_url, _database_conninfo
from repository import ChronicleReadRepository
from router import dispatch


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
        raise AssertionError(f"expected one {collection} record with {field}={value!r}, got {matches}")
    return matches[0]


def _direct_claim_payloads(bundle: dict, kind: str, ref: str) -> list[dict]:
    result = []
    for claim in bundle["claims"]:
        subject = claim.get("subject") or {}
        obj = claim.get("object") or {}
        if (subject.get("kind") == kind and subject.get("ref") == ref) or (
            obj.get("kind") == kind and obj.get("ref") == ref
        ):
            result.append(claim)
    return sorted(result, key=record_ref)


class ChronicleReadModelRealDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundles, cls.resolutions, cls.catalog = _load_dataset()
        cls.entity_membership = _membership(cls.catalog, "canonical_entities")
        cls.event_membership = _membership(cls.catalog, "canonical_events")
        cls.control_url = _control_url()
        cls.database_name = f"chronicle_read_{uuid.uuid4().hex}"
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
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(cls.database_name))
            )

    def _repo(self):
        conn = psycopg.connect(self.database_url)
        conn.execute("BEGIN READ ONLY")
        return conn, ChronicleReadRepository(conn)

    def test_timeline_returns_canonical_red_cliffs_once(self) -> None:
        wudi_ref = _find_ref(self.bundles["wudi"], "events", "title", "赤壁之战")
        wuzhu_ref = _find_ref(self.bundles["wuzhu"], "events", "title", "赤壁之战")
        red_cliffs_id = self.event_membership[("wudi", wudi_ref)]
        self.assertEqual(red_cliffs_id, self.event_membership[("wuzhu", wuzhu_ref)])

        conn, repo = self._repo()
        try:
            timeline = repo.timeline(limit=200)
            self.assertEqual(timeline["page"]["total"], 45)
            matches = [item for item in timeline["items"] if item["canonical_event_id"] == red_cliffs_id]
            self.assertEqual(len(matches), 1)
            card = matches[0]
            self.assertEqual(card["display"]["title"], "赤壁之战")
            self.assertEqual(card["representation_count"], 2)
            self.assertEqual(card["source_count"], 2)
            self.assertEqual(card["time"]["start_year"], 208)
            self.assertEqual(card["time"]["end_year"], 208)

            year_208 = repo.timeline(from_year=208, to_year=208, limit=200)
            self.assertEqual(
                len([item for item in year_208["items"] if item["canonical_event_id"] == red_cliffs_id]),
                1,
            )
        finally:
            conn.close()

    def test_red_cliffs_detail_preserves_both_sources_and_exact_claims(self) -> None:
        refs = {
            label: _find_ref(bundle, "events", "title", "赤壁之战")
            for label, bundle in self.bundles.items()
        }
        red_cliffs_id = self.event_membership[("wudi", refs["wudi"])]

        conn, repo = self._repo()
        try:
            detail = repo.event_detail(red_cliffs_id)
            self.assertEqual(detail["canonical_event_id"], red_cliffs_id)
            self.assertEqual(detail["display"]["title"], "赤壁之战")
            self.assertEqual({item["bundle"] for item in detail["representations"]}, {"wudi", "wuzhu"})
            total_claims = 0
            for representation in detail["representations"]:
                label = representation["bundle"]
                ref = refs[label]
                self.assertEqual(representation["source"]["record"], self.bundles[label]["source"])
                self.assertEqual(representation["event"], next(
                    event for event in self.bundles[label]["events"] if record_ref(event) == ref
                ))
                actual_claims = [item["claim"] for item in representation["claims"]]
                expected_claims = _direct_claim_payloads(self.bundles[label], "event_ref", ref)
                self.assertEqual(actual_claims, expected_claims)
                total_claims += len(actual_claims)
                for claim in actual_claims:
                    self.assertTrue(claim["evidence"]["text"])
                    self.assertEqual(claim["evidence"]["source_ref"], "src_001")
            self.assertGreater(total_claims, 0)
            self.assertIn("participants", detail)
            self.assertIn("places", detail)
            self.assertTrue(any(link["decision"] == "same_occurrence" for link in detail["resolution_links"]))
        finally:
            conn.close()

    def test_jiangling_events_remain_distinct_and_related(self) -> None:
        titles = ("曹操进军江陵", "曹操北还并留军守江陵、襄阳")
        refs = {}
        ids = {}
        for label, title in zip(("wudi", "wuzhu"), titles):
            refs[label] = _find_ref(self.bundles[label], "events", "title", title)
            ids[label] = self.event_membership[(label, refs[label])]
        self.assertNotEqual(ids["wudi"], ids["wuzhu"])

        conn, repo = self._repo()
        try:
            left = repo.event_detail(ids["wudi"])
            right = repo.event_detail(ids["wuzhu"])
            self.assertIn(ids["wuzhu"], {item["event"]["canonical_event_id"] for item in left["related_events"]})
            self.assertIn(ids["wudi"], {item["event"]["canonical_event_id"] for item in right["related_events"]})
            self.assertTrue(any(item["type"] == "related_occurrence" for item in left["related_events"]))
            self.assertTrue(any(link["decision"] == "related_occurrence" for link in left["resolution_links"]))
        finally:
            conn.close()

    def test_cao_cao_entity_aggregates_sources_and_claims(self) -> None:
        refs = {
            label: _find_ref(bundle, "entities", "canonical_name", "曹操")
            for label, bundle in self.bundles.items()
        }
        cao_cao_id = self.entity_membership[("wudi", refs["wudi"])]
        self.assertEqual(cao_cao_id, self.entity_membership[("wuzhu", refs["wuzhu"])] )

        conn, repo = self._repo()
        try:
            detail = repo.entity_detail(cao_cao_id)
            self.assertEqual(detail["display"]["name"], "曹操")
            self.assertEqual(detail["representation_count"], 2)
            self.assertEqual({item["bundle"] for item in detail["representations"]}, {"wudi", "wuzhu"})
            self.assertGreater(len(detail["events"]), 0)
            for representation in detail["representations"]:
                label = representation["bundle"]
                expected = _direct_claim_payloads(self.bundles[label], "entity_ref", refs[label])
                self.assertEqual([item["claim"] for item in representation["claims"]], expected)
            self.assertTrue(any(link["decision"] == "same_entity" for link in detail["resolution_links"]))
        finally:
            conn.close()

    def test_uncertain_places_remain_distinct_and_visible(self) -> None:
        conn, repo = self._repo()
        try:
            for name in ("襄阳", "夏口", "江陵", "赤壁", "合肥"):
                refs = {
                    label: _find_ref(bundle, "entities", "canonical_name", name)
                    for label, bundle in self.bundles.items()
                }
                ids = {
                    label: self.entity_membership[(label, refs[label])]
                    for label in self.bundles
                }
                self.assertNotEqual(ids["wudi"], ids["wuzhu"], name)
                for label in ("wudi", "wuzhu"):
                    detail = repo.entity_detail(ids[label])
                    self.assertEqual(detail["display"]["name"], name)
                    uncertain = [link for link in detail["resolution_links"] if link["decision"] == "uncertain"]
                    self.assertEqual(len(uncertain), 1, name)
                    linked_ids = {
                        uncertain[0]["left"]["canonical_entity_id"],
                        uncertain[0]["right"]["canonical_entity_id"],
                    }
                    self.assertEqual(linked_ids, {ids["wudi"], ids["wuzhu"]}, name)
        finally:
            conn.close()

    def test_router_contracts(self) -> None:
        conn, repo = self._repo()
        try:
            status, timeline = dispatch(repo, "GET", "/v0/timeline", "from_year=208&to_year=208&limit=200")
            self.assertEqual(status, 200)
            self.assertEqual(timeline["schema"], "chronicle.timeline")

            status, payload = dispatch(repo, "GET", "/v0/events/not-a-uuid")
            self.assertEqual(status, 400)
            self.assertEqual(payload["error"]["code"], "bad_request")

            status, payload = dispatch(
                repo,
                "GET",
                "/v0/entities/00000000-0000-4000-8000-000000000000",
            )
            self.assertEqual(status, 404)
            self.assertEqual(payload["error"]["code"], "not_found")

            status, payload = dispatch(repo, "POST", "/v0/timeline")
            self.assertEqual(status, 405)
            self.assertEqual(payload["error"]["code"], "method_not_allowed")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
