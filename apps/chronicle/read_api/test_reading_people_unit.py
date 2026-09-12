"""Unit tests for the C2-R3-T09 source-reading person-state domain API.

No database: routing, query/parameter validation, cursor and store error
classification, context-membership consistency and the response-size budget are
exercised with patched T05 read entries and DTO-shaped pages. Real PostgreSQL
keyset/visibility behavior lives in ``test_reading_people_postgres.py``.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PERSISTENCE = HERE.parent / "persistence"
for candidate in (str(HERE), str(PERSISTENCE)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import person_state_contract as P  # noqa: E402
import reading_people as people  # noqa: E402
from common import PersistenceError  # noqa: E402

SHA = "a" * 64
OTHER_SHA = "b" * 64
STREAM = "019535d9-3df7-7000-8000-0000000000aa"
UNIT = "ru_" + "0" * 24
PERSON = "019535d9-3df7-7000-8000-0000000000bb"
OTHER_PERSON = "019535d9-3df7-7000-8000-0000000000cc"
PUBLICATION = "019535d9-3df7-7000-8000-0000000000dd"
CHAPTER = "ch_" + "1" * 24
REVISION = "019535d9-3df7-7000-8000-0000000000ee"

PEOPLE_PATH = f"/v0/reading-streams/{STREAM}/units/{UNIT}/people"
STATES_PATH = f"/v0/reading-streams/{STREAM}/units/{UNIT}/people/{PERSON}/states"


def _phase(phase_id: str = "ph_001", ordinal: int = 0) -> dict:
    return P.example_phase_summary(
        phase_id=phase_id, label="初", ordinal=ordinal, mode="single"
    )


def _source_fact(phase_id: str = "ph_001") -> dict:
    return P.example_source_fact_ref(
        chapter_publication_id=PUBLICATION,
        chapter_id=CHAPTER,
        revision_id=REVISION,
        fact_ref="pf_001",
        phase_id=phase_id,
    )


def _item(person_id: str = PERSON, *, fact_ref: str = "pf_001", name: str = "建威中郎將") -> dict:
    return P.example_state_item(
        person_id=person_id,
        dimension="office",
        value=name,
        certainty="clear",
        phase_ids=["ph_001"],
        source_facts=[_source_fact()],
        chapter_id=CHAPTER,
        fact_ref=fact_ref,
        current=True,
    )


def _change(person_id: str = PERSON) -> dict:
    return P.example_state_change(
        person_id=person_id,
        dimension="office",
        value="偏將軍",
        operation="start",
        to_phase_id="ph_002",
        from_phase_id="ph_001",
        chapter_id=CHAPTER,
        fact_ref="pf_002",
        source_facts=[_source_fact("ph_002")],
    )


def _person(person_id: str = PERSON, *, name: str = "周瑜", identities=None, changes=None) -> dict:
    identities = identities if identities is not None else [_item(person_id)]
    return P.example_person_summary(
        person_id=person_id,
        name=name,
        identities=identities,
        changes=changes,
    )


def _summary_page(people_list, *, limit: int = 6, next_cursor=None) -> dict:
    return P.example_unit_people_page(
        stream_id=STREAM,
        unit_id=UNIT,
        catalog_sha=SHA,
        publication_id=PUBLICATION,
        state_manifest_sha=OTHER_SHA,
        phase_mode="single",
        phases=[_phase()],
        people=people_list,
        limit=limit,
        next_cursor=next_cursor,
    )


def _states_page(*, section: str = "identities", items=None, changes=None, next_cursor=None) -> dict:
    return P.example_person_state_page(
        stream_id=STREAM,
        unit_id=UNIT,
        catalog_sha=SHA,
        publication_id=PUBLICATION,
        state_manifest_sha=OTHER_SHA,
        person_id=PERSON,
        section=section,
        phase_id=None,
        phases=[_phase()],
        items=items,
        changes=changes,
        next_cursor=next_cursor,
    )


def _evidence_page(descriptors, *, next_cursor=None) -> dict:
    return P.example_state_evidence_page(
        stream_id=STREAM,
        unit_id=UNIT,
        catalog_sha=SHA,
        publication_id=PUBLICATION,
        state_manifest_sha=OTHER_SHA,
        item_id=_item()["item_id"],
        phase_id=None,
        descriptors=descriptors,
        next_cursor=next_cursor,
    )


def _descriptor(index: int) -> dict:
    return P.example_evidence_descriptor(
        descriptor_id=f"desc_{index}",
        source_publication_id=PUBLICATION,
        anchor_id="anc_" + uuid.uuid4().hex[:16],
        quote=f"瑜為前部大督-{index}",
        source_title="周瑜傳",
        phase_id="ph_001",
    )


def _unit_with(*person_ids: str) -> dict:
    return {
        "unit_id": UNIT,
        "context_entities": [
            {"kind": "person", "canonical_id": person_id, "name": person_id}
            for person_id in person_ids
        ],
    }


class RouteAndMethodTests(unittest.TestCase):
    def test_unrelated_and_malformed_routes_return_none(self) -> None:
        for path in (
            "/v0/history",
            f"/v0/reading-streams/{STREAM}",
            f"/v0/reading-streams/{STREAM}/units/{UNIT}",
            f"/v0/reading-streams/{STREAM}/units/{UNIT}/people/{PERSON}",
            f"/v0/reading-streams/{STREAM}/units/{UNIT}/people/{PERSON}/states/extra",
        ):
            self.assertIsNone(people.dispatch_reading_people(None, "GET", path))

    def test_matched_routes_are_matched(self) -> None:
        route = people._match_route(PEOPLE_PATH)
        self.assertEqual("people", route["kind"])
        route = people._match_route(STATES_PATH)
        self.assertEqual("states", route["kind"])
        self.assertEqual(PERSON, route["person_id"])

    def test_non_get_is_405(self) -> None:
        for path in (PEOPLE_PATH, STATES_PATH):
            status, body = people.dispatch_reading_people(None, "POST", path)
            self.assertEqual(405, status)
            self.assertEqual("method_not_allowed", body["error"]["code"])

    def test_query_parameter_validation(self) -> None:
        status, body = people.dispatch_reading_people(
            None, "GET", PEOPLE_PATH, "bogus=1"
        )
        self.assertEqual(400, status)
        status, body = people.dispatch_reading_people(
            None, "GET", PEOPLE_PATH, f"catalog={SHA}&catalog={SHA}"
        )
        self.assertEqual(400, status)
        self.assertIn("appear once", body["error"]["message"])

    def test_states_route_requires_section(self) -> None:
        status, body = people.dispatch_reading_people(
            None, "GET", STATES_PATH, f"catalog={SHA}"
        )
        self.assertEqual(400, status)
        self.assertIn("section is required", body["error"]["message"])


class ParameterValidationTests(unittest.TestCase):
    def test_unit_people_parameters(self) -> None:
        for kwargs, message in (
            ({"stream_id": "not-a-uuid", "unit_id": UNIT}, "stream_id"),
            ({"stream_id": STREAM, "unit_id": ""}, "unit_id"),
            ({"stream_id": STREAM, "unit_id": UNIT, "limit": 0}, "limit"),
            ({"stream_id": STREAM, "unit_id": UNIT, "limit": 51}, "limit"),
            ({"stream_id": STREAM, "unit_id": UNIT, "limit": True}, "limit"),
            ({"stream_id": STREAM, "unit_id": UNIT, "catalog_sha": "zz"}, "catalog"),
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(people.ReadingPeopleBadRequest) as ctx:
                    people.unit_people(None, **kwargs)
                self.assertIn(message, str(ctx.exception))

    def test_person_states_section_and_item_contract(self) -> None:
        base = {
            "stream_id": STREAM,
            "unit_id": UNIT,
            "person_id": PERSON,
            "catalog_sha": SHA,
        }
        with self.assertRaises(people.ReadingPeopleBadRequest):
            people.unit_person_states(None, section="bogus", **base)
        with self.assertRaises(people.ReadingPeopleBadRequest) as ctx:
            people.unit_person_states(None, section="evidence", **base)
        self.assertIn("requires item_id", str(ctx.exception))
        with self.assertRaises(people.ReadingPeopleBadRequest) as ctx:
            people.unit_person_states(None, section="identities", item_id="psi_" + "0" * 24, **base)
        self.assertIn("only valid", str(ctx.exception))
        with self.assertRaises(people.ReadingPeopleBadRequest):
            people.unit_person_states(None, section="evidence", item_id="nope", **base)
        with self.assertRaises(people.ReadingPeopleBadRequest):
            people.unit_person_states(
                None, section="identities", phase_id="not-a-phase", **base
            )
        with self.assertRaises(people.ReadingPeopleBadRequest):
            people.unit_person_states(None, section="identities", limit=0, **base)


class ErrorClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.patches = [
            mock.patch.object(
                people._reading_store,
                "read_reading_unit",
                return_value=_unit_with(PERSON),
            ),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_cursor_error_is_400(self) -> None:
        with mock.patch.object(
            people._store,
            "list_unit_people",
            side_effect=people._store.PersonStateCursorError("cursor belongs to another scope"),
        ):
            with self.assertRaises(people.ReadingPeopleBadRequest):
                people.unit_people(None, stream_id=STREAM, unit_id=UNIT, catalog_sha=SHA)

    def test_unknown_member_is_404(self) -> None:
        for message in ("unknown person 'x' in stream s unit u", "not visible in snapshot s"):
            with self.subTest(message=message):
                with mock.patch.object(
                    people._store, "list_unit_people", side_effect=PersistenceError(message)
                ):
                    with self.assertRaises(people.ReadingPeopleNotFound):
                        people.unit_people(None, stream_id=STREAM, unit_id=UNIT, catalog_sha=SHA)

    def test_missing_manifest_is_409(self) -> None:
        for message in (
            "unknown person-state manifest for stream s unit u",
            "person-state manifest for stream s does not cover unit ru_0",
        ):
            with self.subTest(message=message):
                with mock.patch.object(
                    people._store, "list_unit_people", side_effect=PersistenceError(message)
                ):
                    with self.assertRaises(people.ReadingPeopleInconsistent):
                        people.unit_people(None, stream_id=STREAM, unit_id=UNIT, catalog_sha=SHA)

    def test_person_outside_unit_context_is_409(self) -> None:
        with mock.patch.object(
            people._reading_store, "read_reading_unit", return_value=_unit_with(OTHER_PERSON)
        ), mock.patch.object(
            people._store, "list_unit_people", return_value=_summary_page([_person()])
        ):
            with self.assertRaises(people.ReadingPeopleInconsistent):
                people.unit_people(None, stream_id=STREAM, unit_id=UNIT, catalog_sha=SHA)

    def test_states_person_outside_context_is_404(self) -> None:
        with mock.patch.object(
            people._reading_store, "read_reading_unit", return_value=_unit_with(OTHER_PERSON)
        ), mock.patch.object(
            people._store, "list_unit_person_states"
        ) as store_call:
            with self.assertRaises(people.ReadingPeopleNotFound):
                people.unit_person_states(
                    None,
                    stream_id=STREAM,
                    unit_id=UNIT,
                    person_id=PERSON,
                    section="identities",
                    catalog_sha=SHA,
                )
            store_call.assert_not_called()


class ResponseShapeAndBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        patch = mock.patch.object(
            people._reading_store, "read_reading_unit", return_value=_unit_with(PERSON)
        )
        patch.start()
        self.addCleanup(patch.stop)

    def test_summary_returns_validated_page(self) -> None:
        with mock.patch.object(
            people._store, "list_unit_people", return_value=_summary_page([_person()])
        ):
            page = people.unit_people(None, stream_id=STREAM, unit_id=UNIT, catalog_sha=SHA)
        self.assertEqual(1, page["people_count"])

    def test_summary_invalid_dto_is_409(self) -> None:
        broken = _summary_page([_person()])
        broken["people"][0].pop("name")
        with mock.patch.object(people._store, "list_unit_people", return_value=broken):
            with self.assertRaises(people.ReadingPeopleInconsistent):
                people.unit_people(None, stream_id=STREAM, unit_id=UNIT, catalog_sha=SHA)

    def test_summary_oversized_item_is_409(self) -> None:
        oversized = _item(name="x" * 70000)
        with mock.patch.object(
            people._store, "list_unit_people",
            return_value=_summary_page([_person(identities=[oversized])]),
        ):
            with self.assertRaises(people.ReadingPeopleInconsistent) as ctx:
                people.unit_people(None, stream_id=STREAM, unit_id=UNIT, catalog_sha=SHA)
        self.assertIn("compiled_item_max_bytes", str(ctx.exception))

    def test_detail_oversized_item_is_409(self) -> None:
        oversized = _item(name="x" * 70000)
        with mock.patch.object(
            people._store, "list_unit_person_states",
            return_value=_states_page(items=[oversized]),
        ):
            with self.assertRaises(people.ReadingPeopleInconsistent) as ctx:
                people.unit_person_states(
                    None, stream_id=STREAM, unit_id=UNIT, person_id=PERSON,
                    section="identities", catalog_sha=SHA,
                )
        self.assertIn("compiled_item_max_bytes", str(ctx.exception))

    def test_summary_budget_drops_whole_people_and_keeps_cursor(self) -> None:
        huge = "字" * 20000
        all_people = [_person(name=huge), _person(name=huge), _person(name=huge)]
        calls: list[int] = []

        def fake(conn, *, stream_id, unit_id, catalog_sha, limit, cursor):
            calls.append(limit)
            kept = all_people[:limit]
            next_cursor = "cursor" if limit < len(all_people) else None
            return _summary_page(kept, limit=limit, next_cursor=next_cursor)

        with mock.patch.object(people._store, "list_unit_people", side_effect=fake):
            page = people.unit_people(None, stream_id=STREAM, unit_id=UNIT, catalog_sha=SHA, limit=3)
        self.assertEqual([3, 2], calls)
        self.assertEqual(2, page["people_count"])
        self.assertEqual("cursor", page["next_cursor"])
        self.assertTrue(page["has_more"])

    def test_states_and_evidence_pages(self) -> None:
        item = _item()
        with mock.patch.object(
            people._store,
            "list_unit_person_states",
            return_value=_states_page(items=[item]),
        ):
            page = people.unit_person_states(
                None, stream_id=STREAM, unit_id=UNIT, person_id=PERSON,
                section="identities", catalog_sha=SHA,
            )
        self.assertEqual("identities", page["section"])
        with mock.patch.object(
            people._store,
            "list_unit_person_states",
            return_value=_states_page(section="changes", changes=[_change()]),
        ):
            page = people.unit_person_states(
                None, stream_id=STREAM, unit_id=UNIT, person_id=PERSON,
                section="changes", catalog_sha=SHA,
            )
        self.assertEqual("changes", page["section"])
        with mock.patch.object(
            people._store,
            "list_state_item_evidence",
            return_value=_evidence_page([_descriptor(0), _descriptor(1)]),
        ):
            page = people.unit_person_states(
                None, stream_id=STREAM, unit_id=UNIT, person_id=PERSON,
                section="evidence", item_id=item["item_id"], catalog_sha=SHA,
            )
        self.assertEqual(2, page["descriptor_count"])

    def test_evidence_budget_drops_whole_descriptors(self) -> None:
        long_quote = "甲" * 18000
        descriptors = [
            P.example_evidence_descriptor(
                descriptor_id=f"desc_{index}",
                source_publication_id=PUBLICATION,
                anchor_id="anc_" + f"{index:016d}",
                quote=long_quote,
                source_title="周瑜傳",
                phase_id="ph_001",
            )
            for index in range(3)
        ]
        calls: list[int] = []

        def fake(conn, *, stream_id, unit_id, person_id, item_id, phase_id, catalog_sha, limit, cursor):
            calls.append(limit)
            kept = descriptors[:limit]
            return _evidence_page(kept, next_cursor="more" if limit < len(descriptors) else None)

        with mock.patch.object(people._store, "list_state_item_evidence", side_effect=fake):
            page = people.unit_person_states(
                None, stream_id=STREAM, unit_id=UNIT, person_id=PERSON,
                section="evidence", item_id=_item()["item_id"], catalog_sha=SHA, limit=3,
            )
        self.assertEqual([3, 1], calls)
        self.assertEqual(1, page["descriptor_count"])
        self.assertEqual("more", page["next_cursor"])


if __name__ == "__main__":
    unittest.main()
