"""PostgreSQL 18 integration tests for the C2-R2-T09 public reading router.

``continuous-reading.md`` §6 fixes one HTTP boundary: browsers call the Rust
``/api/v1/public/reading-*`` surface, the Python sidecar serves the matching
``/v0/reading-*`` contracts, and the existing Event/Entity details accept an
optional snapshot ``catalog``. These tests exercise the Python router (the
authority for path/parameter/error mapping) on top of the real T05/T08
persistence entries:

- the seven new reading routes reach the T07/T08 domain queries and echo the
  resolved snapshot;
- unknown/repeated/invalid parameters, bad UUIDs and a missing ``catalog`` on
  snapshot-scoped previews are 400; unknown streams/events and routes are 404;
  non-GET is 405;
- a snapshot-scoped Event/Entity detail never carries the unbounded "latest"
  Reader Presentation overlay, while the no-catalog call keeps it.

The stream/event fixtures are seeded through ``reading_store`` and the real
control-plane rows; that is a test loading path, not a second production
success path.
"""

from __future__ import annotations

import json
import sys
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg import sql

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PERSISTENCE = ROOT / "apps" / "chronicle" / "persistence"
for path in (PERSISTENCE, HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import test_reading_events_postgres as base  # noqa: E402
from migrations import apply_migrations  # noqa: E402
from repository import ChronicleReadRepository  # noqa: E402
import router as read_router  # noqa: E402


class ReadingRouterPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = base._control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_t09_router_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name))
            )
        self.database_url = base._database_conninfo(self.control_url, self.database_name)
        self.conn = psycopg.connect(self.database_url)
        apply_migrations(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(self.database_name)
                )
            )

    # Borrow the T08 fixture builders (staged bundles/catalogs, chapter
    # publications and reading streams) without re-running its domain tests.
    _seed_bundle_event = base.ReadingEventsPostgresTests._seed_bundle_event
    _seed_catalog = base.ReadingEventsPostgresTests._seed_catalog
    _seed_publication = base.ReadingEventsPostgresTests._seed_publication
    _persist_stream = base.ReadingEventsPostgresTests._persist_stream
    _span_occurrence = base.ReadingEventsPostgresTests._span_occurrence

    # -- helpers -------------------------------------------------------

    def _dispatch(self, method: str, path: str, query: str = ""):
        repo = ChronicleReadRepository(self.conn)
        return read_router.dispatch(repo, method, path, query)

    def _seed_single_event(self) -> dict:
        event_id = base._uuid7()
        catalog = self._seed_catalog(
            [
                {
                    "canonical_id": event_id,
                    "title": "赤壁之战",
                    "members": [
                        {"bundle": "book-a", "ref": "evt_a", "source_title": "甲书"}
                    ],
                }
            ]
        )
        ctx = self._seed_publication(
            label="a", title="甲书", blocks=["甲书记赤壁之战。"], catalog_sha=catalog
        )
        self._publish_occurrence(ctx, catalog, event_id)
        return {"event_id": event_id, "catalog": catalog, "ctx": ctx}

    def _publish_occurrence(self, ctx: dict, catalog: str, event_id: str) -> None:
        self._persist_stream(
            ctx,
            catalog_sha=catalog,
            unit_specs=[
                {
                    "text": ctx["blocks"][0]["text"],
                    "span": {"span_id": "sp_a", "quote": "赤壁之战"},
                    "occurrences": [
                        self._span_occurrence(
                            canonical_id=event_id,
                            bundle="book-a",
                            ref="evt_a",
                            span_id="sp_a",
                            relation="current",
                        )
                    ],
                }
            ],
        )

    # -- route coverage ------------------------------------------------

    def test_reading_stream_routes_reach_domain_queries(self) -> None:
        seeded = self._seed_single_event()
        catalog = seeded["catalog"]
        ctx = seeded["ctx"]
        unit_id = "ru_" + base._sha256(f"{ctx['label']}:0")[:24]

        status, payload = self._dispatch(
            "GET", "/v0/reading-streams", f"catalog={catalog}&limit=10"
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["snapshot"]["catalog_sha"], catalog)
        self.assertEqual(len(payload["page"]["streams"]), 1)
        stream = payload["page"]["streams"][0]
        stream_id = stream["stream_id"]

        status, detail = self._dispatch(
            "GET", f"/v0/reading-streams/{stream_id}", f"catalog={catalog}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(detail["page"]["stream_id"], stream_id)
        self.assertEqual(detail["page"]["unit_count"], 1)

        status, units = self._dispatch(
            "GET", f"/v0/reading-streams/{stream_id}/units", f"catalog={catalog}"
        )
        self.assertEqual(status, 200)
        self.assertEqual([u["unit_id"] for u in units["page"]["units"]], [unit_id])

        status, groups = self._dispatch(
            "GET", f"/v0/reading-streams/{stream_id}/groups", f"catalog={catalog}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(groups["page"]["groups"]), 1)

        status, located = self._dispatch(
            "GET",
            f"/v0/reading-streams/{stream_id}/locate",
            f"catalog={catalog}&unit_id={unit_id}",
        )
        self.assertEqual(status, 200)
        self.assertEqual(located["page"]["locator"]["unit_id"], unit_id)
        self.assertEqual(located["page"]["units"][0]["unit_id"], unit_id)

    def test_reading_event_preview_and_targets_routes(self) -> None:
        seeded = self._seed_single_event()
        event_id = seeded["event_id"]
        catalog = seeded["catalog"]

        status, preview = self._dispatch(
            "GET", f"/v0/reading-events/{event_id}/preview", f"catalog={catalog}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(preview["event_id"], event_id)
        self.assertEqual(preview["catalog_sha"], catalog)

        status, targets = self._dispatch(
            "GET", f"/v0/reading-events/{event_id}/targets", f"catalog={catalog}&limit=5"
        )
        self.assertEqual(status, 200)
        self.assertEqual([t["span_id"] for t in targets["targets"]], ["sp_a"])

    # -- validation / errors -------------------------------------------

    def test_bad_parameters_and_methods(self) -> None:
        seeded = self._seed_single_event()
        catalog = seeded["catalog"]
        event_id = seeded["event_id"]

        # Unknown and repeated parameters are 400, never silently ignored.
        status, payload = self._dispatch("GET", "/v0/reading-streams", "bogus=1")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "bad_request")

        status, _ = self._dispatch("GET", "/v0/reading-streams", "limit=1&limit=2")
        self.assertEqual(status, 400)

        # Invalid catalog shape and invalid UUID are 400.
        status, _ = self._dispatch("GET", "/v0/reading-streams", "catalog=not-a-sha")
        self.assertEqual(status, 400)
        status, _ = self._dispatch("GET", "/v0/reading-streams/not-a-uuid", f"catalog={catalog}")
        self.assertEqual(status, 400)

        # Snapshot-scoped preview requires an explicit catalog.
        status, _ = self._dispatch("GET", f"/v0/reading-events/{event_id}/preview")
        self.assertEqual(status, 400)

        # Unknown but well-formed streams/events and unknown subroutes are 404.
        unknown = "01a08df4-64ee-7c14-9273-1306e41578bd"
        status, _ = self._dispatch("GET", f"/v0/reading-streams/{unknown}", f"catalog={catalog}")
        self.assertEqual(status, 404)
        status, _ = self._dispatch(
            "GET", f"/v0/reading-events/{unknown}/preview", f"catalog={catalog}"
        )
        self.assertEqual(status, 404)
        status, _ = self._dispatch(
            "GET", f"/v0/reading-streams/{unknown}/bogus", f"catalog={catalog}"
        )
        self.assertEqual(status, 404)

        # Non-GET is a typed 405.
        status, payload = self._dispatch("POST", "/v0/reading-streams", f"catalog={catalog}")
        self.assertEqual(status, 405)
        self.assertEqual(payload["error"]["code"], "method_not_allowed")

    def test_unknown_snapshot_catalog_is_not_found(self) -> None:
        seeded = self._seed_single_event()
        event_id = seeded["event_id"]
        missing = "0" * 64
        status, _ = self._dispatch(
            "GET", f"/v0/reading-events/{event_id}/preview", f"catalog={missing}"
        )
        self.assertEqual(status, 404)

    # -- optional snapshot on Event/Entity details ---------------------

    def _insert_published_presentation(self, canonical_event_id: str) -> str:
        presentation_id = str(uuid.uuid4())
        self.conn.execute(
            """
            INSERT INTO chronicle.reader_presentations(
                presentation_id, target_kind, canonical_event_id, base_language,
                contract_version, presentation_version, status, generator_version,
                model_version, prompt_version, input_fingerprint, content_sha256
            ) VALUES (%s, 'event', %s, 'zh-CN', '0.1', 1, 'published',
                      'g', 'm', 'p', %s, %s)
            """,
            (presentation_id, canonical_event_id, "a" * 64, "b" * 64),
        )
        return presentation_id

    def test_event_detail_optional_snapshot_suppresses_latest_overlay(self) -> None:
        seeded = self._seed_single_event()
        event_id = seeded["event_id"]
        catalog = seeded["catalog"]
        presentation_id = self._insert_published_presentation(event_id)

        status, unscoped = self._dispatch("GET", f"/v0/events/{event_id}")
        self.assertEqual(status, 200)
        self.assertIsNotNone(unscoped["reader_presentation"])
        self.assertEqual(
            unscoped["reader_presentation"]["presentation_id"], presentation_id
        )

        status, scoped = self._dispatch("GET", f"/v0/events/{event_id}", f"catalog={catalog}")
        self.assertEqual(status, 200)
        self.assertIsNone(scoped["reader_presentation"])
        self.assertEqual(scoped["canonical_event_id"], event_id)

    def test_event_and_entity_detail_catalog_validation(self) -> None:
        seeded = self._seed_single_event()
        event_id = seeded["event_id"]
        catalog = seeded["catalog"]

        status, payload = self._dispatch("GET", f"/v0/events/{event_id}", "catalog=not-a-sha")
        self.assertEqual(status, 400)

        status, _ = self._dispatch("GET", f"/v0/events/{event_id}", "bogus=1")
        self.assertEqual(status, 400)

        status, _ = self._dispatch("GET", f"/v0/events/{event_id}", f"catalog={'0' * 64}")
        self.assertEqual(status, 404)

        unknown = "01a08df4-64ee-7c14-9273-1306e41578bd"
        status, _ = self._dispatch("GET", f"/v0/entities/{unknown}", f"catalog={catalog}")
        self.assertEqual(status, 404)

        # The no-catalog Entity route keeps its original behavior.
        status, _ = self._dispatch("GET", f"/v0/entities/{unknown}")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
