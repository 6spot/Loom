"""C1-T15 Historical Moment PostgreSQL contracts."""

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
from historical_moment import build_historical_moment
from migrations import apply_migrations
from postgres_v0 import persist_dataset
from repository import ChronicleReadRepository
from router import dispatch
from test_postgres_v0 import _control_url, _database_conninfo


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
        raise AssertionError(
            f"expected one {collection} record with {field}={value!r}, got {matches}"
        )
    return matches[0]


class HistoricalMomentPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundles, cls.resolutions, cls.catalog = _load_dataset()
        cls.event_membership = _membership(cls.catalog, "canonical_events")
        cls.control_url = _control_url()
        cls.database_name = f"chronicle_moment_{uuid.uuid4().hex}"
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

    @classmethod
    def tearDownClass(cls) -> None:
        with psycopg.connect(cls.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(cls.database_name)
                )
            )

    def _repo(self):
        conn = psycopg.connect(self.database_url, autocommit=True)
        conn.execute("BEGIN READ ONLY")
        return conn, ChronicleReadRepository(conn)

    def test_208_moment_is_grounded_deterministic_and_traceable(self) -> None:
        wudi_ref = _find_ref(self.bundles["wudi"], "events", "title", "赤壁之战")
        wuzhu_ref = _find_ref(self.bundles["wuzhu"], "events", "title", "赤壁之战")
        red_cliffs_id = self.event_membership[("wudi", wudi_ref)]
        self.assertEqual(red_cliffs_id, self.event_membership[("wuzhu", wuzhu_ref)])

        conn, _ = self._repo()
        try:
            first = build_historical_moment(conn, year=208, limit=100)
            second = build_historical_moment(conn, year=208, limit=100)
            self.assertEqual(first, second)
            self.assertEqual(first["schema"], "chronicle.historical-moment")
            self.assertFalse(first["authority"]["historical_world_state"])
            self.assertFalse(first["authority"]["historical_truth"])
            self.assertFalse(first["authority"]["mutates_history"])
            self.assertEqual(first["query"]["from_year"], 208)
            self.assertEqual(first["query"]["to_year"], 208)

            event = next(
                item
                for item in first["events"]
                if item["canonical_event_id"] == red_cliffs_id
            )
            self.assertEqual(event["display"]["title"], "赤壁之战")
            self.assertEqual(event["time"]["observed_years"], [208])
            self.assertEqual(event["time"]["status"], "single_observed_year")
            self.assertEqual(event["source_count"], 2)
            self.assertEqual(
                {item["bundle"] for item in event["representations"]},
                {"wudi", "wuzhu"},
            )
            self.assertGreater(len(event["claims"]), 0)
            for claim in event["claims"]:
                evidence = claim["claim"].get("evidence") or {}
                self.assertTrue(evidence.get("text"))
                self.assertTrue(evidence.get("source_ref"))
                self.assertTrue(claim["source"]["title"])

            self.assertEqual(
                [item["year"] for item in first["coverage"]["time"]["years"]],
                [208],
            )
            self.assertGreater(
                first["coverage"]["time"]["years"][0]["event_count"], 0
            )
            self.assertTrue(first["uncertainty"]["absence_is_not_historical_absence"])
            self.assertTrue(any(
                relation["as_place"]
                for place in first["places"]
                for relation in place["relations"]
                if relation["canonical_event_id"] == red_cliffs_id
            ))

            forbidden = {
                "territorial_control",
                "precise_person_locations",
                "troop_counts",
                "political_ownership",
                "complete_world_state",
            }
            self.assertTrue(forbidden.isdisjoint(first))
        finally:
            conn.close()

    def test_neighboring_year_keeps_sparse_or_empty_state_explicit(self) -> None:
        conn, _ = self._repo()
        try:
            moment = build_historical_moment(conn, year=209, limit=100)
            self.assertEqual(moment["query"]["kind"], "year")
            self.assertEqual(
                [item["year"] for item in moment["coverage"]["time"]["years"]],
                [209],
            )
            density = moment["coverage"]["time"]["years"][0]["density"]
            self.assertIn(density, {"unrepresented", "sparse", "represented"})
            if not moment["events"]:
                self.assertEqual(density, "unrepresented")
                self.assertTrue(
                    moment["uncertainty"]["absence_is_not_historical_absence"]
                )
        finally:
            conn.close()

    def test_period_and_pagination_validation(self) -> None:
        conn, _ = self._repo()
        try:
            with self.assertRaisesRegex(Exception, "provide year"):
                build_historical_moment(conn)
            with self.assertRaisesRegex(Exception, "cannot be combined"):
                build_historical_moment(conn, year=208, from_year=208, to_year=209)
            with self.assertRaisesRegex(Exception, "at most 100 years"):
                build_historical_moment(conn, from_year=1, to_year=101)
            with self.assertRaisesRegex(Exception, "limit must be between"):
                build_historical_moment(conn, year=208, limit=0)
        finally:
            conn.close()

    def test_router_contract(self) -> None:
        conn, repo = self._repo()
        try:
            status, payload = dispatch(
                repo,
                "GET",
                "/v0/historical-moment",
                "year=208&limit=100",
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload["schema"], "chronicle.historical-moment")

            status, payload = dispatch(
                repo,
                "GET",
                "/v0/historical-moment",
                "year=208&from_year=208&to_year=209",
            )
            self.assertEqual(status, 400)
            self.assertEqual(payload["error"]["code"], "bad_request")

            status, payload = dispatch(
                repo,
                "GET",
                "/v0/historical-moment",
                "year=208&unexpected=true",
            )
            self.assertEqual(status, 400)
            self.assertEqual(payload["error"]["code"], "bad_request")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
