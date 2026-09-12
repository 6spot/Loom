"""PostgreSQL 18 integration tests for the C2-R3-T10 public person-state routes.

T10 wires the T09 source-reading domain queries into the single public Python
router: browsers call the Rust ``/api/v1/public/reading-streams/.../people``
surface, the sidecar serves the matching ``/v0/reading-streams/...`` contract,
and the T05 person-state store remains the only read authority. These tests
exercise the Python router on top of the real T05/T08 persistence entries:

- the summary, states (identities/changes) and evidence routes reach the T09
  domain queries and echo the resolved snapshot/person locator;
- unknown/repeated/invalid parameters and a bad ``phase_id`` are 400; an
  unknown stream/person/item and an unknown subroute are 404; non-GET is 405;
- a cursor issued for another snapshot is rejected as 400 before it can leak;
- the deeper ``units/.../people`` path must not be swallowed by the generic
  reading-streams matcher (it previously returned a blanket 404).

Fixtures seed real control-plane / chapter / catalog / reading-stream rows and
persist the manifest through the production T05 write entry; that is a test
loading path, not a second production success path.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg import sql

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PERSISTENCE = ROOT / "apps" / "chronicle" / "persistence"
for path in (str(HERE), str(PERSISTENCE)):
    if path not in sys.path:
        sys.path.insert(0, str(path))

import test_reading_people_postgres as base  # noqa: E402
from migrations import apply_migrations  # noqa: E402
from repository import ChronicleReadRepository  # noqa: E402
import router as read_router  # noqa: E402


class PersonStateRouterPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = base._control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_t10_router_{uuid.uuid4().hex}"
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

    # Borrow the T09 fixture builders without re-running its domain tests.
    _seed_catalog = base.ReadingPeoplePostgresTests._seed_catalog
    _seed_source = base.ReadingPeoplePostgresTests._seed_source
    _build_stream = base.ReadingPeoplePostgresTests._build_stream
    _setup_stream = base.ReadingPeoplePostgresTests._setup_stream
    _source_fact = base.ReadingPeoplePostgresTests._source_fact
    _item = base.ReadingPeoplePostgresTests._item
    _change = base.ReadingPeoplePostgresTests._change
    _descriptor = base.ReadingPeoplePostgresTests._descriptor
    _person = base.ReadingPeoplePostgresTests._person
    _unit = base.ReadingPeoplePostgresTests._unit
    _manifest = base.ReadingPeoplePostgresTests._manifest
    _persist = base.ReadingPeoplePostgresTests._persist
    _context = staticmethod(base.ReadingPeoplePostgresTests._context)

    # -- helpers -------------------------------------------------------

    def _dispatch(self, method: str, path: str, query: str = ""):
        repo = ChronicleReadRepository(self.conn)
        return read_router.dispatch(repo, method, path, query)

    def _seed_unit(self, *, context_person_count: int = 1):
        catalog = self._seed_catalog(self.conn, tag="c1")
        person_ids = [base._uuid7() for _ in range(context_person_count)]
        ctx, stream_id = self._setup_stream(
            self.conn,
            label="zhou",
            blocks=["瑜字公瑾"],
            catalog_sha=catalog,
            tag="v1",
            context_by_unit={"ru_zhou_0": self._context(*person_ids)},
        )
        item = self._item(ctx, person_ids[0], fact_ref="pf_001")
        compiled_people = []
        for index, person_id in enumerate(person_ids):
            person_item = (
                item
                if index == 0
                else self._item(ctx, person_id, fact_ref=f"pf_{index + 1:03d}")
            )
            compiled_people.append(
                self._person(
                    person_id,
                    "周瑜" if index == 0 else f"人物{index}",
                    items=[person_item],
                    changes=(
                        [self._change(ctx, person_id, fact_ref="pf_002")]
                        if index == 0
                        else []
                    ),
                    evidence=(
                        [
                            {
                                "item_id": item["item_id"],
                                "descriptors": [
                                    self._descriptor(ctx, n) for n in range(3)
                                ],
                            }
                        ]
                        if index == 0
                        else []
                    ),
                )
            )
        self._persist(
            ctx,
            stream_id,
            [
                self._unit(
                    ctx,
                    unit_id="ru_zhou_0",
                    unit_ordinal=0,
                    people=compiled_people,
                )
            ],
        )
        return {
            "catalog": catalog,
            "stream_id": stream_id,
            "person_id": person_ids[0],
            "item_id": item["item_id"],
            "ctx": ctx,
        }

    def _people_path(self, stream_id: str) -> str:
        return f"/v0/reading-streams/{stream_id}/units/ru_zhou_0/people"

    # -- route coverage ------------------------------------------------

    def test_person_state_routes_are_wired_and_echo_the_locator(self) -> None:
        seeded = self._seed_unit()
        catalog = seeded["catalog"]
        stream_id = seeded["stream_id"]
        person_id = seeded["person_id"]
        item_id = seeded["item_id"]

        status, page = self._dispatch(
            "GET", self._people_path(stream_id), f"catalog={catalog}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(catalog, page["catalog_sha"])
        self.assertEqual(stream_id, page["stream_id"])
        self.assertEqual(1, page["people_count"])
        self.assertEqual(person_id, page["people"][0]["person_id"])

        status, identities = self._dispatch(
            "GET",
            f"{self._people_path(stream_id)}/{person_id}/states",
            f"catalog={catalog}&section=identities",
        )
        self.assertEqual(status, 200)
        self.assertEqual("identities", identities["section"])
        self.assertEqual(1, identities["item_count"])

        status, changes = self._dispatch(
            "GET",
            f"{self._people_path(stream_id)}/{person_id}/states",
            f"catalog={catalog}&section=changes",
        )
        self.assertEqual(status, 200)
        self.assertEqual("changes", changes["section"])
        self.assertEqual(1, changes["item_count"])

        status, evidence = self._dispatch(
            "GET",
            f"{self._people_path(stream_id)}/{person_id}/states",
            f"catalog={catalog}&section=evidence&item_id={item_id}&limit=2",
        )
        self.assertEqual(status, 200)
        self.assertEqual("evidence", evidence["section"])
        self.assertEqual(2, len(evidence["descriptors"]))
        self.assertTrue(evidence["has_more"])

        # An omitted catalog resolves and echoes the newest snapshot exactly once.
        status, defaulted = self._dispatch("GET", self._people_path(stream_id))
        self.assertEqual(status, 200)
        self.assertEqual(catalog, defaulted["catalog_sha"])

        # The generic reading-streams routes are untouched by the new wiring.
        status, detail = self._dispatch(
            "GET", f"/v0/reading-streams/{stream_id}", f"catalog={catalog}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(detail["page"]["stream_id"], stream_id)

    def test_person_state_parameter_and_route_errors(self) -> None:
        seeded = self._seed_unit(context_person_count=2)
        catalog = seeded["catalog"]
        stream_id = seeded["stream_id"]
        person_id = seeded["person_id"]
        people_path = self._people_path(stream_id)

        # limit out of range / non-integer is 400.
        status, payload = self._dispatch(
            "GET", people_path, f"catalog={catalog}&limit=0"
        )
        self.assertEqual(400, status)
        self.assertEqual("bad_request", payload["error"]["code"])

        # Repeated and unknown parameters are 400, never silently ignored.
        status, _ = self._dispatch(
            "GET", people_path, f"catalog={catalog}&limit=1&limit=2"
        )
        self.assertEqual(400, status)
        status, _ = self._dispatch("GET", people_path, f"catalog={catalog}&bogus=1")
        self.assertEqual(400, status)

        # A malformed catalog and an unknown but well-formed stream are distinct.
        status, _ = self._dispatch("GET", people_path, "catalog=not-a-sha")
        self.assertEqual(400, status)
        unknown_stream = "01a08df4-64ee-7c14-9273-1306e41578bd"
        status, _ = self._dispatch(
            "GET", self._people_path(unknown_stream), f"catalog={catalog}"
        )
        self.assertEqual(404, status)

        # section is required and phase_id/cursor bind to this page scope.
        states_path = f"{people_path}/{person_id}/states"
        status, payload = self._dispatch("GET", states_path, f"catalog={catalog}")
        self.assertEqual(400, status)
        self.assertIn("section is required", payload["error"]["message"])
        status, _ = self._dispatch(
            "GET", states_path, f"catalog={catalog}&section=identities&phase_id=ph_9"
        )
        self.assertEqual(400, status)

        # An outsider person and an unknown item are 404, never a content leak.
        outsider = base._uuid7()
        status, _ = self._dispatch(
            "GET",
            f"{people_path}/{outsider}/states",
            f"catalog={catalog}&section=identities",
        )
        self.assertEqual(404, status)
        status, _ = self._dispatch(
            "GET",
            states_path,
            f"catalog={catalog}&section=evidence&item_id=psi_{'0' * 24}",
        )
        self.assertEqual(404, status)

        # An unknown subroute stays 404; non-GET stays a typed 405.
        status, _ = self._dispatch(
            "GET", f"{people_path}/bogus", f"catalog={catalog}"
        )
        self.assertEqual(404, status)
        status, payload = self._dispatch("POST", people_path, f"catalog={catalog}")
        self.assertEqual(405, status)
        self.assertEqual("method_not_allowed", payload["error"]["code"])

    def test_person_state_cursor_is_snapshot_scoped(self) -> None:
        seeded = self._seed_unit(context_person_count=2)
        catalog = seeded["catalog"]
        stream_id = seeded["stream_id"]

        status, first = self._dispatch(
            "GET", self._people_path(stream_id), f"catalog={catalog}&limit=1"
        )
        self.assertEqual(200, status)
        self.assertTrue(first["has_more"])
        cursor = first["next_cursor"]

        other_catalog = self._seed_catalog(self.conn, tag="c2")
        status, payload = self._dispatch(
            "GET",
            self._people_path(stream_id),
            f"catalog={other_catalog}&limit=1&cursor={cursor}",
        )
        self.assertEqual(400, status)
        self.assertEqual("bad_request", payload["error"]["code"])


if __name__ == "__main__":
    unittest.main()
