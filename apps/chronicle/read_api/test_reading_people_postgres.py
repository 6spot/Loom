"""PostgreSQL 18 integration tests for the C2-R3-T09 source person-state API.

Covers ``person-state-reading.md`` section 7 on top of the real T05 store:

- the summary/state/evidence pages are bounded keysets that reach every entry
  exactly once without reading the whole history;
- a cursor from another stream/unit/person/phase/catalog is rejected before it
  can leak;
- only persons present in the reading unit's own ``context_entities`` are
  served, and a manifest that lists an outside person is an explicit 409;
- an older snapshot never sees a later state manifest, while a newer catalog's
  recorded disagreement overlays as ``uncertain`` / ``source_disagreement``;
- every GET is read-only.

Fixtures seed real control-plane / chapter / catalog / reading-stream rows and
persist the manifest through the production T05 write entry; that is a test
loading path, not a second production success path.
"""

from __future__ import annotations

import hashlib
import json
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
PERSISTENCE = ROOT / "apps" / "chronicle" / "persistence"
for path in (str(HERE), str(PERSISTENCE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import canonical_store  # noqa: E402
import control_plane  # noqa: E402
import person_state_contract as P  # noqa: E402
import person_state_store as store  # noqa: E402
import reading_people as people  # noqa: E402
import reading_store  # noqa: E402
from common import PersistenceError  # noqa: E402
from migrations import apply_migrations  # noqa: E402

DEFAULT_CONTROL_URL = "postgresql://loom:loom@127.0.0.1:15432/loom_control"

_UUID_COUNTER = [9000]


def _uuid7() -> str:
    _UUID_COUNTER[0] += 1
    n = _UUID_COUNTER[0]
    value = (0x019535D93DF7 << 80) | (0x7 << 76) | ((n & 0xFFF) << 64) | (0b10 << 62) | n
    return str(uuid.UUID(int=value))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


class ReadingPeoplePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_t09_people_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        self.database_url = _database_conninfo(self.control_url, self.database_name)
        self.conn = psycopg.connect(self.database_url)
        apply_migrations(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name))
            )

    # -- reading fixtures (real control plane / chapter / catalog / stream) --

    def _seed_catalog(self, conn, *, tag: str) -> str:
        catalog = {
            "schema": "chronicle.canonical-catalog",
            "version": "0.1",
            "tag": tag,
            "canonical_entities": [],
            "canonical_events": [],
            "event_relations": [],
            "warnings": [],
        }
        catalog_sha, _ = canonical_store.persist_catalog(conn, catalog)
        return catalog_sha

    def _seed_source(self, conn, *, label: str, title: str, blocks: list[str], catalog_sha: str) -> dict:
        document_id = control_plane.create_document(conn, title=title)
        revision_id, revision_no = control_plane.create_revision(
            conn,
            document_id=document_id,
            source_sha256=_sha256(f"{label}-source"),
            source_bytes=len("".join(blocks).encode("utf-8")),
            source_media_type="text/markdown",
        )
        worker = f"worker-{label}"
        job_id = control_plane.queue_job(conn, revision_id=revision_id)
        control_plane.claim_job(conn, worker=worker, job_id=job_id)
        section_id = control_plane.create_section(
            conn, job_id=job_id, section_index=0, label="章",
            source_start=0, source_end=len("".join(blocks)),
        )
        chunk_id = control_plane.record_chunk(
            conn, job_id=job_id, section_id=section_id, chunk_index=0,
            source_start=0, source_end=len("".join(blocks)),
            source_sha256=_sha256(f"{label}-source"),
            content_sha256=_sha256(f"{label}-chunk"),
        )
        control_plane.set_chunk_status(conn, chunk_id=chunk_id, status="running")
        run_id, _ = control_plane.record_chunk_run(conn, chunk_id=chunk_id, status="running", worker=worker)
        chapter_id = f"ch_{_sha256(label)[:24]}"
        artifact_sha256 = _sha256(f"{label}-artifact")
        blocks_payload = [
            {"block_id": f"t_{index:03d}", "text": text}
            for index, text in enumerate(blocks, start=1)
        ]
        conn.execute(
            """
            INSERT INTO chronicle.chapter_artifacts(
                artifact_sha256, job_id, revision_id, document_id, chapter_id,
                chapter_index, chunk_id, producing_run_id, request_fingerprint,
                candidate_sha256, payload
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                artifact_sha256, job_id, revision_id, document_id, chapter_id, 0,
                chunk_id, run_id, _sha256(f"{label}-fingerprint"),
                _sha256(f"{label}-candidate"), json.dumps({"seed": True}),
            ),
        )
        publication_id = _uuid7()
        publication = {
            "schema": "chronicle.chapter-publication",
            "version": "0.1",
            "chapter_id": chapter_id,
            "chapter_index": 0,
            "revision_id": str(revision_id),
            "artifact_sha256": artifact_sha256,
            "catalog_sha256": catalog_sha,
            "assembled_bundle_sha256": _sha256(f"{label}-assembled"),
            "translation_blocks": blocks_payload,
        }
        conn.execute(
            """
            INSERT INTO chronicle.chapter_publications(
                publication_id, artifact_sha256, catalog_sha256,
                assembled_bundle_sha256, document_id, revision_id, job_id,
                chapter_id, payload
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                publication_id, artifact_sha256, catalog_sha,
                publication["assembled_bundle_sha256"], document_id,
                revision_id, job_id, chapter_id, json.dumps(publication),
            ),
        )
        return {
            "label": label,
            "document_id": document_id,
            "revision_id": revision_id,
            "revision_no": revision_no,
            "job_id": job_id,
            "chapter_id": chapter_id,
            "artifact_sha256": artifact_sha256,
            "publication_id": publication_id,
            "blocks": blocks_payload,
        }

    def _build_stream(self, ctx: dict, *, catalog_sha: str, tag: str, context_by_unit: dict) -> dict:
        units: list[dict] = []
        groups: list[dict] = []
        for index, block in enumerate(ctx["blocks"]):
            unit_id = f"ru_{ctx['label']}_{index}"
            text = block["text"]
            units.append(
                {
                    "unit_id": unit_id,
                    "ordinal": index,
                    "publication_id": str(ctx["publication_id"]),
                    "artifact_sha256": ctx["artifact_sha256"],
                    "chapter_id": ctx["chapter_id"],
                    "block_id": block["block_id"],
                    "text_hash": _sha256(text),
                    "narrative_time": {
                        "mode": "events", "status": "resolved", "event_refs": [],
                        "from_block_id": None, "observations": [],
                        "year_key": f"gregorian:{208 + index}",
                        "period_key": f"gregorian:{208 + index}",
                        "year_label": f"{208 + index}年",
                        "period_label": "（月份未明确）",
                        "precision": "year", "continues_previous": False,
                    },
                    "segments": [{"kind": "text", "text": text}],
                    "context_entities": context_by_unit.get(unit_id, []),
                    "source_anchor_ids": [f"anc_{block['block_id']}"],
                    "group_id": f"tg_{ctx['label']}_{index}",
                    "continues_previous": False,
                }
            )
            groups.append(
                {
                    "ordinal": index,
                    "group_id": f"tg_{ctx['label']}_{index}",
                    "first_unit_ordinal": index,
                    "last_unit_ordinal": index,
                    "first_unit_id": unit_id,
                    "last_unit_id": unit_id,
                    "unit_count": 1,
                    "year_key": f"gregorian:{208 + index}",
                    "period_key": f"gregorian:{208 + index}",
                    "year_label": f"{208 + index}年",
                    "period_label": "（月份未明确）",
                    "precision": "year",
                    "observations": [],
                    "continues_previous": False,
                }
            )
        manifest = {
            "schema": "chronicle.reading-stream",
            "version": "0.1",
            "tag": tag,
            "revision_id": str(ctx["revision_id"]),
            "catalog_sha256": catalog_sha,
            "unit_ids": [unit["unit_id"] for unit in units],
            "group_ids": [group["group_id"] for group in groups],
        }
        return {
            "revision_id": str(ctx["revision_id"]),
            "document_id": str(ctx["document_id"]),
            "origin_catalog_sha": catalog_sha,
            "manifest": manifest,
            "chapter_publication_ids": [str(ctx["publication_id"])],
            "units": units,
            "groups": groups,
            "event_occurrences": [],
        }

    def _setup_stream(self, conn, *, label, blocks, catalog_sha, tag, context_by_unit=None):
        ctx = self._seed_source(conn, label=label, title=label, blocks=blocks, catalog_sha=catalog_sha)
        stream_id = reading_store.persist_reading_stream(
            conn, self._build_stream(ctx, catalog_sha=catalog_sha, tag=tag, context_by_unit=context_by_unit or {})
        )
        return ctx, str(stream_id)

    # -- person-state input builders ---------------------------------------

    def _source_fact(self, ctx, fact_ref, phase_id="ph_001"):
        return {
            "chapter_publication_id": str(ctx["publication_id"]),
            "chapter_id": ctx["chapter_id"],
            "revision_id": str(ctx["revision_id"]),
            "fact_ref": fact_ref,
            "claim_refs": [],
            "phase_id": phase_id,
        }

    def _item(self, ctx, person_id, *, fact_ref, phase_id="ph_001", dimension="office",
              value="建威中郎將", operation="attest", qualification="ordinary",
              certainty="clear", current=True, reason_codes=None):
        return {
            "item_id": P.item_id_for(
                chapter_id=ctx["chapter_id"], fact_ref=fact_ref, dimension=dimension,
                phase_id=phase_id, person_ref=person_id, operation=operation,
            ),
            "person_id": person_id,
            "dimension": dimension,
            "value": value,
            "relation": None,
            "target": None,
            "target_id": None,
            "qualification": qualification,
            "certainty": certainty,
            "reason_codes": sorted(reason_codes or []),
            "phase_ids": [phase_id],
            "current": current,
            "source_facts": [self._source_fact(ctx, fact_ref, phase_id)],
            "evidence_count": 0,
            "evidence_cursor": None,
        }

    def _change(self, ctx, person_id, *, fact_ref, to_phase_id="ph_002", from_phase_id="ph_001",
                dimension="office", value="偏將軍", operation="start", certainty="clear"):
        return {
            "item_id": P.item_id_for(
                chapter_id=ctx["chapter_id"], fact_ref=fact_ref, dimension=dimension,
                phase_id=to_phase_id, person_ref=person_id, operation=operation,
            ),
            "person_id": person_id,
            "dimension": dimension,
            "value": value,
            "relation": None,
            "target": None,
            "operation": operation,
            "from_phase_id": from_phase_id,
            "to_phase_id": to_phase_id,
            "certainty": certainty,
            "reason_codes": [],
            "source_facts": [self._source_fact(ctx, fact_ref, to_phase_id)],
        }

    def _descriptor(self, ctx, index, phase_id="ph_001"):
        quote = f"瑜為前部大督-{index}"
        return {
            "descriptor_id": f"desc_{ctx['label']}_{index}",
            "source_publication_id": str(ctx["publication_id"]),
            "anchor_id": "anc_" + hashlib.sha256(quote.encode()).hexdigest()[:16],
            "quote": quote,
            "quote_sha256": _sha256(quote),
            "attribution": "narrator",
            "source_title": "周瑜傳",
            "phase_id": phase_id,
            "relation": "support",
        }

    def _person(self, person_id, name, *, items, changes=None, evidence=None,
                importance="primary", certainty="clear", reason_codes=None):
        return {
            "person_id": person_id,
            "name": name,
            "importance": importance,
            "certainty": certainty,
            "reason_codes": sorted(reason_codes or []),
            "items": items,
            "changes": changes or [],
            "evidence": evidence or [],
        }

    def _unit(self, ctx, *, unit_id, unit_ordinal, people, phase_mode="single", phases=None):
        return {
            "unit_id": unit_id,
            "unit_ordinal": unit_ordinal,
            "publication_id": str(ctx["publication_id"]),
            "phase_mode": phase_mode,
            "phases": phases or [{"phase_id": "ph_001", "label": "初", "ordinal": 0, "mode": "single"}],
            "people": people,
        }

    def _manifest(self, ctx, stream_id, *, units, manifest_payload=None):
        return {
            "stream_id": stream_id,
            "compiler_version": "person-state-compiler/0.1",
            "assessment_hashes": [],
            "chapter_publication_ids": [str(ctx["publication_id"])],
            "manifest": manifest_payload
            or {"schema": "chronicle.person-state-manifest", "version": "0.1", "tag": ctx["label"]},
            "units": units,
        }

    def _persist(self, ctx, stream_id, units, *, manifest_payload=None):
        return store.persist_person_state_manifest(
            conn=self.conn,
            manifest=self._manifest(ctx, stream_id, units=units, manifest_payload=manifest_payload),
        )

    @staticmethod
    def _context(*person_ids: str) -> list[dict]:
        return [
            {
                "entity_ref": f"ent_{index:03d}",
                "name": person_id,
                "canonical_id": person_id,
                "kind": "person",
                "importance": "primary",
                "source_anchor_ids": [],
                "event_roles": [],
            }
            for index, person_id in enumerate(person_ids, start=1)
        ]

    # -- tests --------------------------------------------------------------

    def test_summary_states_and_evidence_round_trip(self) -> None:
        catalog = self._seed_catalog(self.conn, tag="c1")
        person_a, person_b = _uuid7(), _uuid7()
        ctx, stream_id = self._setup_stream(
            self.conn,
            label="zhou",
            blocks=["瑜字公瑾"],
            catalog_sha=catalog,
            tag="v1",
            context_by_unit={"ru_zhou_0": self._context(person_a, person_b)},
        )
        unit_id = "ru_zhou_0"
        item_a = self._item(ctx, person_a, fact_ref="pf_001")
        descriptors = [self._descriptor(ctx, index) for index in range(20)]
        self._persist(
            ctx,
            stream_id,
            [
                self._unit(
                    ctx,
                    unit_id=unit_id,
                    unit_ordinal=0,
                    phases=[
                        {"phase_id": "ph_001", "label": "初", "ordinal": 0, "mode": "single"},
                        {"phase_id": "ph_002", "label": "後", "ordinal": 1, "mode": "single"},
                    ],
                    people=[
                        self._person(
                            person_a, "周瑜",
                            items=[item_a, self._item(ctx, person_a, fact_ref="pf_003", value="前部大督")],
                            changes=[self._change(ctx, person_a, fact_ref="pf_002")],
                            evidence=[{"item_id": item_a["item_id"], "descriptors": descriptors}],
                        ),
                        self._person(person_b, "魯肅", items=[self._item(ctx, person_b, fact_ref="pf_004")], importance="other"),
                    ],
                )
            ],
        )

        page = people.unit_people(self.conn, stream_id=stream_id, unit_id=unit_id, catalog_sha=catalog)
        self.assertEqual(2, page["people_count"])
        self.assertEqual({person_a, person_b}, {p["person_id"] for p in page["people"]})
        self.assertEqual(catalog, page["catalog_sha"])

        identities = people.unit_person_states(
            self.conn, stream_id=stream_id, unit_id=unit_id, person_id=person_a,
            section="identities", catalog_sha=catalog,
        )
        self.assertEqual("identities", identities["section"])
        self.assertEqual(2, identities["item_count"])

        phase_only = people.unit_person_states(
            self.conn, stream_id=stream_id, unit_id=unit_id, person_id=person_a,
            section="identities", phase_id="ph_002", catalog_sha=catalog,
        )
        self.assertEqual(0, phase_only["item_count"])

        changes = people.unit_person_states(
            self.conn, stream_id=stream_id, unit_id=unit_id, person_id=person_a,
            section="changes", catalog_sha=catalog,
        )
        self.assertEqual(1, changes["item_count"])

        seen: list[str] = []
        cursor = None
        while True:
            evidence = people.unit_person_states(
                self.conn, stream_id=stream_id, unit_id=unit_id, person_id=person_a,
                section="evidence", item_id=item_a["item_id"],
                catalog_sha=catalog, limit=8, cursor=cursor,
            )
            seen.extend(descriptor["descriptor_id"] for descriptor in evidence["descriptors"])
            self.assertLessEqual(len(evidence["descriptors"]), 8)
            if not evidence["has_more"]:
                break
            cursor = evidence["next_cursor"]
        self.assertEqual(20, len(seen))
        self.assertEqual(20, len(set(seen)))

    def test_people_keyset_reaches_everyone_once(self) -> None:
        catalog = self._seed_catalog(self.conn, tag="c1")
        person_ids = [_uuid7() for _ in range(7)]
        ctx, stream_id = self._setup_stream(
            self.conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=catalog, tag="v1",
            context_by_unit={"ru_zhou_0": self._context(*person_ids)},
        )
        people_units = [
            self._person(person_id, f"人物{index}", items=[self._item(ctx, person_id, fact_ref=f"pf_{index:03d}")])
            for index, person_id in enumerate(person_ids)
        ]
        self._persist(ctx, stream_id, [self._unit(ctx, unit_id="ru_zhou_0", unit_ordinal=0, people=people_units)])

        seen: list[str] = []
        cursor = None
        while True:
            page = people.unit_people(
                self.conn, stream_id=stream_id, unit_id="ru_zhou_0",
                catalog_sha=catalog, limit=2, cursor=cursor,
            )
            seen.extend(person["person_id"] for person in page["people"])
            if not page["has_more"]:
                break
            cursor = page["next_cursor"]
        self.assertEqual(sorted(person_ids), sorted(seen))

    def test_catalog_defaults_to_newest_snapshot(self) -> None:
        catalog = self._seed_catalog(self.conn, tag="c1")
        person_a = _uuid7()
        ctx, stream_id = self._setup_stream(
            self.conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=catalog, tag="v1",
            context_by_unit={"ru_zhou_0": self._context(person_a)},
        )
        self._persist(ctx, stream_id, [self._unit(ctx, unit_id="ru_zhou_0", unit_ordinal=0, people=[
            self._person(person_a, "周瑜", items=[self._item(ctx, person_a, fact_ref="pf_001")]),
        ])])
        page = people.unit_people(self.conn, stream_id=stream_id, unit_id="ru_zhou_0")
        self.assertEqual(catalog, page["catalog_sha"])
        self.assertEqual(1, page["people_count"])

    def test_cursor_scope_isolation(self) -> None:
        catalog = self._seed_catalog(self.conn, tag="c1")
        person_a, person_b = _uuid7(), _uuid7()
        ctx, stream_id = self._setup_stream(
            self.conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=catalog, tag="v1",
            context_by_unit={"ru_zhou_0": self._context(person_a, person_b)},
        )
        self._persist(
            ctx, stream_id,
            [self._unit(ctx, unit_id="ru_zhou_0", unit_ordinal=0, people=[
                self._person(person_a, "周瑜", items=[self._item(ctx, person_a, fact_ref="pf_001")]),
                self._person(person_b, "魯肅", items=[self._item(ctx, person_b, fact_ref="pf_002")], importance="other"),
            ])],
        )
        first = people.unit_people(self.conn, stream_id=stream_id, unit_id="ru_zhou_0", catalog_sha=catalog, limit=1)
        self.assertTrue(first["has_more"])
        cursor = first["next_cursor"]
        # Replaying the summary cursor under a different catalog is a 400.
        other_catalog = self._seed_catalog(self.conn, tag="c2")
        with self.assertRaises(people.ReadingPeopleBadRequest):
            people.unit_people(
                self.conn, stream_id=stream_id, unit_id="ru_zhou_0",
                catalog_sha=other_catalog, limit=1, cursor=cursor,
            )

    def test_empty_unit_returns_an_empty_page(self) -> None:
        catalog = self._seed_catalog(self.conn, tag="c1")
        ctx, stream_id = self._setup_stream(
            self.conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=catalog, tag="v1",
            context_by_unit={"ru_zhou_0": []},
        )
        self._persist(ctx, stream_id, [self._unit(ctx, unit_id="ru_zhou_0", unit_ordinal=0, people=[])])
        page = people.unit_people(self.conn, stream_id=stream_id, unit_id="ru_zhou_0", catalog_sha=catalog)
        self.assertEqual(0, page["people_count"])
        self.assertFalse(page["has_more"])
        self.assertIsNone(page["next_cursor"])

    def test_membership_errors(self) -> None:
        catalog = self._seed_catalog(self.conn, tag="c1")
        person_a, outsider = _uuid7(), _uuid7()
        ctx, stream_id = self._setup_stream(
            self.conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=catalog, tag="v1",
            context_by_unit={"ru_zhou_0": self._context(person_a)},
        )
        item = self._item(ctx, person_a, fact_ref="pf_001")
        self._persist(ctx, stream_id, [self._unit(ctx, unit_id="ru_zhou_0", unit_ordinal=0, people=[
            self._person(person_a, "周瑜", items=[item]),
        ])])
        with self.assertRaises(people.ReadingPeopleNotFound):
            people.unit_person_states(
                self.conn, stream_id=stream_id, unit_id="ru_zhou_0", person_id=outsider,
                section="identities", catalog_sha=catalog,
            )
        with self.assertRaises(people.ReadingPeopleNotFound):
            people.unit_person_states(
                self.conn, stream_id=stream_id, unit_id="ru_zhou_0", person_id=person_a,
                section="identities", phase_id="ph_099", catalog_sha=catalog,
            )
        with self.assertRaises(people.ReadingPeopleNotFound):
            people.unit_person_states(
                self.conn, stream_id=stream_id, unit_id="ru_zhou_0", person_id=person_a,
                section="evidence", item_id="psi_" + "0" * 24, catalog_sha=catalog,
            )

    def test_context_inconsistency_is_409(self) -> None:
        catalog = self._seed_catalog(self.conn, tag="c1")
        person_a, outsider = _uuid7(), _uuid7()
        ctx, stream_id = self._setup_stream(
            self.conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=catalog, tag="v1",
            context_by_unit={"ru_zhou_0": self._context(person_a)},
        )
        self._persist(ctx, stream_id, [self._unit(ctx, unit_id="ru_zhou_0", unit_ordinal=0, people=[
            self._person(outsider, "外人", items=[self._item(ctx, outsider, fact_ref="pf_009")]),
        ])])
        with self.assertRaises(people.ReadingPeopleInconsistent):
            people.unit_people(self.conn, stream_id=stream_id, unit_id="ru_zhou_0", catalog_sha=catalog)

    def test_snapshot_and_disagreement_isolation(self) -> None:
        old_catalog = self._seed_catalog(self.conn, tag="c0")
        origin_catalog = self._seed_catalog(self.conn, tag="c1")
        new_catalog = self._seed_catalog(self.conn, tag="c2")
        person_a = _uuid7()
        ctx, stream_id = self._setup_stream(
            self.conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=origin_catalog, tag="v1",
            context_by_unit={"ru_zhou_0": self._context(person_a)},
        )
        item = self._item(ctx, person_a, fact_ref="pf_001")
        self._persist(ctx, stream_id, [self._unit(ctx, unit_id="ru_zhou_0", unit_ordinal=0, people=[
            self._person(person_a, "周瑜", items=[item]),
        ])])
        # An older snapshot cannot see the stream's later state manifest.
        with self.assertRaises(people.ReadingPeopleNotFound):
            people.unit_people(self.conn, stream_id=stream_id, unit_id="ru_zhou_0", catalog_sha=old_catalog)
        # The origin catalog returns a clear identity.
        clear = people.unit_people(self.conn, stream_id=stream_id, unit_id="ru_zhou_0", catalog_sha=origin_catalog)
        self.assertEqual("clear", clear["people"][0]["identities"][0]["certainty"])

        store.persist_person_state_disagreements(
            self.conn,
            {
                "catalog_sha": new_catalog,
                "compiler_version": "person-state-compiler/0.1",
                "disagreements": [
                    {
                        "disagreement_id": P.disagreement_id_for(
                            catalog_sha=new_catalog, fact_refs=["pf_001", "pf_900"], topic="官職分歧"
                        ),
                        "topic": "官職分歧",
                        "fact_refs": ["pf_001", "pf_900"],
                        "phase_ids": ["ph_001"],
                        "reason_codes": ["source_disagreement"],
                        "sources": [
                            {"fact_ref": "pf_001", "chapter_id": ctx["chapter_id"]},
                            {"fact_ref": "pf_900", "chapter_id": ctx["chapter_id"]},
                        ],
                    }
                ],
            },
        )
        # The newer catalog overlays the recorded disagreement as uncertain on
        # the item read (the summary preview is the frozen compiled page).
        overlaid = people.unit_person_states(
            self.conn, stream_id=stream_id, unit_id="ru_zhou_0", person_id=person_a,
            section="identities", catalog_sha=new_catalog,
        )
        identity = overlaid["items"][0]
        self.assertEqual("uncertain", identity["certainty"])
        self.assertIn("source_disagreement", identity["reason_codes"])
        # Reading again with the origin catalog is unchanged (snapshot isolation).
        again = people.unit_person_states(
            self.conn, stream_id=stream_id, unit_id="ru_zhou_0", person_id=person_a,
            section="identities", catalog_sha=origin_catalog,
        )
        self.assertEqual("clear", again["items"][0]["certainty"])

    def test_reads_are_read_only(self) -> None:
        catalog = self._seed_catalog(self.conn, tag="c1")
        person_a = _uuid7()
        ctx, stream_id = self._setup_stream(
            self.conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=catalog, tag="v1",
            context_by_unit={"ru_zhou_0": self._context(person_a)},
        )
        item = self._item(ctx, person_a, fact_ref="pf_001")
        self._persist(ctx, stream_id, [self._unit(ctx, unit_id="ru_zhou_0", unit_ordinal=0, people=[
            self._person(person_a, "周瑜", items=[item], evidence=[{"item_id": item["item_id"], "descriptors": [self._descriptor(ctx, 0)]}]),
        ])])
        tables = (
            "person_state_assessments", "person_state_manifests",
            "person_state_unit_people", "person_state_items",
            "person_state_item_evidence", "person_state_disagreements",
        )

        def counts() -> dict[str, int]:
            return {
                table: self.conn.execute(f"SELECT count(*) FROM chronicle.{table}").fetchone()[0]
                for table in tables
            }

        before = counts()
        people.unit_people(self.conn, stream_id=stream_id, unit_id="ru_zhou_0", catalog_sha=catalog)
        people.unit_person_states(
            self.conn, stream_id=stream_id, unit_id="ru_zhou_0", person_id=person_a,
            section="identities", catalog_sha=catalog,
        )
        people.unit_person_states(
            self.conn, stream_id=stream_id, unit_id="ru_zhou_0", person_id=person_a,
            section="evidence", item_id=item["item_id"], catalog_sha=catalog,
        )
        self.assertEqual(before, counts())

    def test_dispatcher_error_contract(self) -> None:
        catalog = self._seed_catalog(self.conn, tag="c1")
        person_a = _uuid7()
        ctx, stream_id = self._setup_stream(
            self.conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=catalog, tag="v1",
            context_by_unit={"ru_zhou_0": self._context(person_a)},
        )
        self._persist(ctx, stream_id, [self._unit(ctx, unit_id="ru_zhou_0", unit_ordinal=0, people=[
            self._person(person_a, "周瑜", items=[self._item(ctx, person_a, fact_ref="pf_001")]),
        ])])
        base = f"/v0/reading-streams/{stream_id}/units/ru_zhou_0/people"
        status, body = people.dispatch_reading_people(self.conn, "GET", base, "limit=0")
        self.assertEqual(400, status)
        self.assertEqual("bad_request", body["error"]["code"])
        status, _ = people.dispatch_reading_people(self.conn, "GET", base, "bogus=1")
        self.assertEqual(400, status)
        status, _ = people.dispatch_reading_people(self.conn, "POST", base, "")
        self.assertEqual(405, status)
        status, body = people.dispatch_reading_people(
            self.conn, "GET", f"{base}/{person_a}/states", f"catalog={catalog}"
        )
        self.assertEqual(400, status)
        self.assertIn("section is required", body["error"]["message"])
        status, page = people.dispatch_reading_people(self.conn, "GET", base, f"catalog={catalog}")
        self.assertEqual(200, status)
        self.assertEqual(1, page["people_count"])
        self.assertIsNone(
            people.dispatch_reading_people(self.conn, "GET", f"/v0/reading-streams/{stream_id}")
        )


if __name__ == "__main__":
    unittest.main()
