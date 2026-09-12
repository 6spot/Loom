"""PostgreSQL 18 integration tests for the Chronicle C2-R3-T05 person-state store.

Covers ``person-state-reading.md`` section 6:

- fresh migration + reapply and the nine person-state tables;
- immutable assessment / manifest / unit-person / item / evidence /
  disagreement writes, idempotent replay and different-byte conflicts;
- caller-owned transaction rollback with no residue and mid-transaction
  failure leaving nothing behind;
- cross-stream / cross-unit composite foreign keys and missing-parent
  rejection (unknown stream, unknown assessment, publication outside the
  stream snapshot);
- bounded keyset pagination that reaches every entry for people, items and
  evidence;
- snapshot catalog isolation: an older snapshot never sees a newer stream and
  a person-state disagreement index is only combined with its own catalog.

Fixtures seed real control-plane / chapter / catalog / reading-stream rows so
the store reads real foreign keys; that seed path is an explicit test loading
path, not a second production success path. The production write path is T08's
single publish transaction calling this store.
"""

from __future__ import annotations

import base64
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
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import canonical_store
import control_plane
import person_state_contract as P
import person_state_store as store
import reading_store
from common import PersistenceConflict, PersistenceError
from migrations import apply_migrations

DEFAULT_CONTROL_URL = "postgresql://loom:loom@127.0.0.1:15432/loom_control"

_UUID_COUNTER = [7000]

PERSON_STATE_TABLES = (
    "person_state_assessments",
    "person_state_manifests",
    "person_state_unit_people",
    "person_state_items",
    "person_state_item_evidence",
    "person_state_disagreements",
    "person_state_unit_places",
    "person_state_place_items",
    "person_state_place_item_evidence",
)


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


class PersonStateStorePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_t05_state_{uuid.uuid4().hex}"
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

    # -- reading fixtures (real control plane / chapter / stream rows) -------

    def _seed_source(
        self, conn, *, label: str, title: str, blocks: list[str], catalog_sha: str
    ) -> dict:
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
            conn,
            job_id=job_id,
            section_index=0,
            label="章",
            source_start=0,
            source_end=len("".join(blocks)),
        )
        chunk_id = control_plane.record_chunk(
            conn,
            job_id=job_id,
            section_id=section_id,
            chunk_index=0,
            source_start=0,
            source_end=len("".join(blocks)),
            source_sha256=_sha256(f"{label}-source"),
            content_sha256=_sha256(f"{label}-chunk"),
        )
        control_plane.set_chunk_status(conn, chunk_id=chunk_id, status="running")
        run_id, _ = control_plane.record_chunk_run(
            conn, chunk_id=chunk_id, status="running", worker=worker
        )
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
                artifact_sha256,
                job_id,
                revision_id,
                document_id,
                chapter_id,
                0,
                chunk_id,
                run_id,
                _sha256(f"{label}-fingerprint"),
                _sha256(f"{label}-candidate"),
                json.dumps({"seed": True, "label": label}),
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
                publication_id,
                artifact_sha256,
                catalog_sha,
                publication["assembled_bundle_sha256"],
                document_id,
                revision_id,
                job_id,
                chapter_id,
                json.dumps(publication),
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

    def _build_stream(self, ctx: dict, *, catalog_sha: str, tag: str) -> dict:
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
                        "mode": "events",
                        "status": "resolved",
                        "event_refs": [],
                        "from_block_id": None,
                        "observations": [],
                        "year_key": f"gregorian:{208 + index}",
                        "period_key": f"gregorian:{208 + index}",
                        "year_label": f"{208 + index}年",
                        "period_label": "（月份未明确）",
                        "precision": "year",
                        "continues_previous": False,
                    },
                    "segments": [{"kind": "text", "text": text}],
                    "context_entities": [],
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

    def _setup_stream(
        self, conn, *, label: str, blocks: list[str], catalog_sha: str, tag: str = "v1"
    ) -> tuple[dict, str]:
        ctx = self._seed_source(
            conn, label=label, title=label, blocks=blocks, catalog_sha=catalog_sha
        )
        stream_id = reading_store.persist_reading_stream(
            conn, self._build_stream(ctx, catalog_sha=catalog_sha, tag=tag)
        )
        return ctx, str(stream_id)

    # -- person-state input builders ---------------------------------------

    def _source_fact(self, ctx: dict, fact_ref: str, phase_id: str = "ph_001") -> dict:
        return {
            "chapter_publication_id": str(ctx["publication_id"]),
            "chapter_id": ctx["chapter_id"],
            "revision_id": str(ctx["revision_id"]),
            "fact_ref": fact_ref,
            "claim_refs": [],
            "phase_id": phase_id,
        }

    def _item(
        self,
        ctx: dict,
        person_id: str,
        *,
        fact_ref: str,
        phase_id: str = "ph_001",
        dimension: str = "office",
        value: str | None = "建威中郎將",
        operation: str = "attest",
        qualification: str = "ordinary",
        certainty: str = "clear",
        current: bool = True,
        reason_codes: list[str] | None = None,
    ) -> dict:
        return {
            "item_id": P.item_id_for(
                chapter_id=ctx["chapter_id"],
                fact_ref=fact_ref,
                dimension=dimension,
                phase_id=phase_id,
                person_ref=person_id,
                operation=operation,
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

    def _change(
        self,
        ctx: dict,
        person_id: str,
        *,
        fact_ref: str,
        to_phase_id: str = "ph_002",
        from_phase_id: str | None = "ph_001",
        dimension: str = "office",
        value: str | None = "偏將軍",
        operation: str = "end",
        certainty: str = "clear",
    ) -> dict:
        return {
            "item_id": P.item_id_for(
                chapter_id=ctx["chapter_id"],
                fact_ref=fact_ref,
                dimension=dimension,
                phase_id=to_phase_id,
                person_ref=person_id,
                operation=operation,
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

    def _place_item(
        self,
        ctx: dict,
        place_id: str,
        *,
        fact_ref: str,
        dimension: str = "administration",
        phase_id: str = "ph_001",
        value: str | None = "荊州",
        controller: str | None = "ent_controller",
        certainty: str = "clear",
        current: bool = True,
        reason_codes: list[str] | None = None,
    ) -> dict:
        return P.example_place_state_item(
            place_id=place_id,
            name="荊州",
            dimension=dimension,
            value=value,
            controller=controller,
            certainty=certainty,
            phase_ids=[phase_id],
            source_facts=[self._source_fact(ctx, fact_ref, phase_id)],
            chapter_id=ctx["chapter_id"],
            fact_ref=fact_ref,
            person_ref=place_id,
            reason_codes=reason_codes,
            current=current,
        )

    def _descriptor(self, ctx: dict, index: int, phase_id: str = "ph_001") -> dict:
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

    def _assessment(
        self,
        conn,
        catalog_sha: str,
        *,
        plan: str = "plan-1",
        payload: dict | None = None,
    ) -> str:
        return store.persist_person_state_assessments(
            conn,
            {
                "plan_fingerprint": _sha256(plan),
                "base_catalog_sha": catalog_sha,
                "compiler_version": "person-state-compiler/0.1",
                "payload": payload
                or {"plan_fingerprint": _sha256(plan), "decisions": [{"candidate_id": "c1", "assessment": "supported"}]},
            },
        )[0]

    def _manifest(
        self,
        ctx: dict,
        stream_id: str,
        catalog_sha: str,
        *,
        assessment_hashes: list[str],
        units: list[dict],
        manifest_payload: dict | None = None,
    ) -> dict:
        return {
            "stream_id": stream_id,
            "compiler_version": "person-state-compiler/0.1",
            "assessment_hashes": assessment_hashes,
            "chapter_publication_ids": [str(ctx["publication_id"])],
            "manifest": manifest_payload
            or {"schema": "chronicle.person-state-manifest", "version": "0.1", "tag": ctx["label"]},
            "units": units,
        }

    def _unit(
        self,
        ctx: dict,
        *,
        unit_id: str,
        unit_ordinal: int,
        people: list[dict],
        phase_mode: str = "single",
        phases: list[dict] | None = None,
        places: list[dict] | None = None,
        place_evidence: list[dict] | None = None,
    ) -> dict:
        return {
            "unit_id": unit_id,
            "unit_ordinal": unit_ordinal,
            "publication_id": str(ctx["publication_id"]),
            "phase_mode": phase_mode,
            "phases": phases
            or [{"phase_id": "ph_001", "label": "初", "ordinal": 0, "mode": "single"}],
            "people": people,
            "places": list(places or []),
            "place_evidence": list(place_evidence or []),
        }

    def _person(
        self,
        person_id: str,
        name: str,
        *,
        items: list[dict],
        changes: list[dict] | None = None,
        evidence: list[dict] | None = None,
        importance: str = "primary",
        certainty: str = "clear",
        reason_codes: list[str] | None = None,
    ) -> dict:
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

    def _disagreements(self, catalog_sha: str, entries: list[dict]) -> dict:
        return {
            "catalog_sha": catalog_sha,
            "compiler_version": "person-state-compiler/0.1",
            "disagreements": entries,
        }

    def _disagreement_entry(
        self, ctx: dict, *, fact_refs: list[str], topic: str, reason_codes: list[str] | None = None
    ) -> dict:
        return {
            "disagreement_id": P.disagreement_id_for(
                catalog_sha="0" * 64, fact_refs=fact_refs, topic=topic
            ),
            "topic": topic,
            "fact_refs": fact_refs,
            "phase_ids": ["ph_001"],
            "reason_codes": sorted(reason_codes or ["source_disagreement"]),
            "sources": [
                {"fact_ref": fact_ref, "chapter_id": ctx["chapter_id"]}
                for fact_ref in fact_refs
            ],
        }

    # -- migration -----------------------------------------------------

    def _state_fixture(self, conn) -> dict:
        """Seed one manifest with two people, several items and evidence.

        Person A carries four identities (two bound phases) and two changes,
        person B two identities, and person A's first identity four evidence
        descriptors. Enough to mint and cross-replay every cursor kind.
        """
        catalog_sha = self._seed_catalog(conn, tag="c1")
        ctx, stream_id = self._setup_stream(
            conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=catalog_sha
        )
        assessment_sha = self._assessment(conn, catalog_sha)
        unit_id = "ru_zhou_0"
        person_a = _uuid7()
        person_b = _uuid7()
        a_identities = [
            self._item(ctx, person_a, fact_ref=f"pf_{index:03d}") for index in range(4)
        ]
        a_changes = [
            self._change(
                ctx, person_a, fact_ref=f"pf_{100 + index:03d}", to_phase_id="ph_002"
            )
            for index in range(2)
        ]
        b_identities = [
            self._item(ctx, person_b, fact_ref=f"pf_{200 + index:03d}")
            for index in range(2)
        ]
        descriptors = [self._descriptor(ctx, index) for index in range(4)]
        unit_phases = [
            {"phase_id": "ph_001", "label": "初", "ordinal": 0, "mode": "single"},
            {"phase_id": "ph_002", "label": "後", "ordinal": 1, "mode": "single"},
        ]
        manifest_sha = store.persist_person_state_manifest(
            conn,
            self._manifest(
                ctx,
                stream_id,
                catalog_sha,
                assessment_hashes=[assessment_sha],
                units=[
                    self._unit(
                        ctx,
                        unit_id=unit_id,
                        unit_ordinal=0,
                        phases=unit_phases,
                        people=[
                            self._person(
                                person_a,
                                "周瑜",
                                items=a_identities,
                                changes=a_changes,
                                evidence=[
                                    {
                                        "item_id": a_identities[0]["item_id"],
                                        "descriptors": descriptors,
                                    }
                                ],
                            ),
                            self._person(
                                person_b,
                                "魯肅",
                                items=b_identities,
                                importance="other",
                            ),
                        ],
                    )
                ],
            ),
        )
        return {
            "ctx": ctx,
            "stream_id": stream_id,
            "catalog_sha": catalog_sha,
            "manifest_sha": manifest_sha,
            "unit_id": unit_id,
            "person_a": person_a,
            "person_b": person_b,
            "a_identities": a_identities,
            "b_identities": b_identities,
        }

    def _tamper_cursor(self, cursor: str, **overrides) -> str:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        payload.update(overrides)
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
        return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")

    def test_fresh_migrate_reapply_and_tables(self) -> None:
        with self._connect_ready() as conn:
            apply_migrations(conn)
            names = {
                row[0]
                for row in conn.execute(
                    "SELECT table_name FROM information_schema.tables"
                    " WHERE table_schema = 'chronicle'"
                )
            }
            for table in PERSON_STATE_TABLES:
                self.assertIn(table, names)
            versions = {
                row[0]
                for row in conn.execute("SELECT version FROM chronicle.schema_migrations")
            }
            self.assertIn("0009_chronicle_person_states.sql", versions)
            self.assertIn("0010_chronicle_place_states.sql", versions)

    # -- happy path / idempotency -------------------------------------------

    def test_persist_and_read_bounded(self) -> None:
        with self._connect_ready() as conn:
            catalog_sha = self._seed_catalog(conn, tag="c1")
            ctx, stream_id = self._setup_stream(
                conn, label="zhou", blocks=["瑜字公瑾", "權拜瑜偏將軍"], catalog_sha=catalog_sha
            )
            assessment_sha = self._assessment(conn, catalog_sha)
            person_id = _uuid7()
            identities = [
                self._item(ctx, person_id, fact_ref=f"pf_{index:03d}") for index in range(5)
            ]
            changes = [
                self._change(ctx, person_id, fact_ref="pf_100", to_phase_id="ph_002"),
            ]
            evidence = [
                {
                    "item_id": identities[0]["item_id"],
                    "descriptors": [self._descriptor(ctx, 0), self._descriptor(ctx, 1)],
                }
            ]
            unit_id = "ru_zhou_0"
            manifest = self._manifest(
                ctx,
                stream_id,
                catalog_sha,
                assessment_hashes=[assessment_sha],
                units=[
                    self._unit(
                        ctx,
                        unit_id=unit_id,
                        unit_ordinal=0,
                        people=[
                            self._person(
                                person_id,
                                "周瑜",
                                items=identities,
                                changes=changes,
                                evidence=evidence,
                            )
                        ],
                    )
                ],
            )
            manifest_sha = store.persist_person_state_manifest(conn, manifest)
            self.assertEqual(len(manifest_sha), 64)

            people = store.list_unit_people(
                conn, stream_id=stream_id, unit_id=unit_id, limit=6
            )
            self.assertEqual(people["state_manifest_sha"], manifest_sha)
            self.assertEqual(people["publication_id"], str(ctx["publication_id"]))
            self.assertEqual(people["phase_mode"], "single")
            self.assertEqual(people["people_count"], 1)
            summary = people["people"][0]
            self.assertEqual(summary["person_id"], person_id)
            self.assertEqual(summary["identity_count"], 5)
            self.assertEqual(len(summary["identities"]), 3)
            self.assertTrue(summary["has_more_identities"])
            self.assertEqual(summary["change_count"], 1)
            self.assertFalse(summary["has_more_changes"])

            states = store.list_unit_person_states(
                conn,
                stream_id=stream_id,
                unit_id=unit_id,
                person_id=person_id,
                section="identities",
                limit=20,
            )
            self.assertEqual([item["item_id"] for item in states["items"]], [i["item_id"] for i in identities])
            self.assertEqual(states["item_count"], 5)

            evidence_page = store.list_state_item_evidence(
                conn,
                stream_id=stream_id,
                unit_id=unit_id,
                person_id=person_id,
                item_id=identities[0]["item_id"],
                limit=50,
            )
            self.assertEqual(evidence_page["descriptor_count"], 2)
            self.assertEqual(
                evidence_page["descriptors"][0]["quote_sha256"], _sha256("瑜為前部大督-0")
            )

    def test_place_persist_and_read_bounded(self) -> None:
        with self._connect_ready() as conn:
            catalog_sha = self._seed_catalog(conn, tag="places")
            ctx, stream_id = self._setup_stream(
                conn, label="place", blocks=["荊州"], catalog_sha=catalog_sha
            )
            assessment_sha = self._assessment(conn, catalog_sha, plan="place-plan")
            place_a_admin = self._place_item(
                ctx, "ent_place_a", fact_ref="pf_301", dimension="administration"
            )
            place_a_control = self._place_item(
                ctx,
                "ent_place_a",
                fact_ref="pf_302",
                dimension="control",
                value="周瑜",
            )
            place_b_admin = self._place_item(
                ctx, "ent_place_b", fact_ref="pf_303", dimension="administration"
            )
            place_evidence = [
                {
                    "item_id": place_a_admin["item_id"],
                    "descriptors": [self._descriptor(ctx, 0), self._descriptor(ctx, 1)],
                }
            ]
            unit_id = "ru_place_0"
            manifest = self._manifest(
                ctx,
                stream_id,
                catalog_sha,
                assessment_hashes=[assessment_sha],
                units=[
                    self._unit(
                        ctx,
                        unit_id=unit_id,
                        unit_ordinal=0,
                        people=[],
                        places=[place_a_control, place_b_admin, place_a_admin],
                        place_evidence=place_evidence,
                    )
                ],
            )
            manifest_sha = store.persist_person_state_manifest(conn, manifest)

            first = store.list_unit_places(
                conn, stream_id=stream_id, unit_id=unit_id, limit=2
            )
            self.assertEqual(first["state_manifest_sha"], manifest_sha)
            self.assertEqual(first["section"], "places")
            self.assertEqual(
                [item["dimension"] for item in first["places"]],
                ["administration", "control"],
            )
            self.assertTrue(first["has_more"])
            second = store.list_unit_places(
                conn,
                stream_id=stream_id,
                unit_id=unit_id,
                limit=2,
                cursor=first["next_cursor"],
            )
            self.assertEqual([item["place_id"] for item in second["places"]], ["ent_place_b"])
            self.assertFalse(second["has_more"])
            self.assertEqual(
                [
                    error
                    for item in first["places"] + second["places"]
                    for error in P.validate_person_state_dto("place_state_item", item)
                ],
                [],
            )

            filtered = store.list_unit_places(
                conn,
                stream_id=stream_id,
                unit_id=unit_id,
                place_id="ent_place_a",
                phase_id="ph_001",
                limit=10,
            )
            self.assertEqual(len(filtered["places"]), 2)
            self.assertEqual({item["place_id"] for item in filtered["places"]}, {"ent_place_a"})

            evidence_page = store.list_place_state_item_evidence(
                conn,
                stream_id=stream_id,
                unit_id=unit_id,
                place_id="ent_place_a",
                item_id=place_a_admin["item_id"],
                limit=1,
            )
            self.assertEqual(evidence_page["descriptor_count"], 1)
            self.assertTrue(evidence_page["has_more"])
            evidence_tail = store.list_place_state_item_evidence(
                conn,
                stream_id=stream_id,
                unit_id=unit_id,
                place_id="ent_place_a",
                item_id=place_a_admin["item_id"],
                limit=1,
                cursor=evidence_page["next_cursor"],
            )
            self.assertEqual(evidence_tail["descriptor_count"], 1)
            self.assertFalse(evidence_tail["has_more"])

            immutable_updates = (
                (
                    "UPDATE chronicle.person_state_unit_places SET name = '改写'",
                ),
                (
                    "UPDATE chronicle.person_state_place_items SET value = '改写'",
                ),
                (
                    "UPDATE chronicle.person_state_place_item_evidence SET quote = '改写'",
                ),
            )
            for (statement,) in immutable_updates:
                with self.assertRaises(psycopg.errors.RaiseException):
                    with conn.transaction():
                        conn.execute(statement)

    def test_real_place_compiler_manifest_round_trip(self) -> None:
        import resolve_publish as R
        import staged_store
        from test_resolve_publish_unit import _bundle, _entity
        from test_person_state_projection_unit import fact

        with self._connect_ready() as conn:
            label = "compiled_place"
            bundle = _bundle("synthetic", [_entity("ent_place", "甲地", "place")], [])
            staged_store.persist_bundle(conn, label, bundle)
            catalog, _ = R.publish_with_decisions(
                bundles={label: bundle}, resolutions=[], existing_catalog=None
            )
            catalog_sha, _ = canonical_store.persist_catalog(conn, catalog)
            place_id = catalog["canonical_entities"][0]["canonical_id"]
            ctx = self._seed_source(
                conn, label=label, title="synthetic", blocks=["甲地隶乙郡。", "随后。"],
                catalog_sha=catalog_sha,
            )
            projection = self._build_stream(ctx, catalog_sha=catalog_sha, tag="v1")
            projection["units"][0]["context_entities"] = [{
                "entity_ref": "ent_place", "canonical_id": place_id,
                "kind": "place", "name": "甲地",
            }]
            stream_id = str(reading_store.persist_reading_stream(conn, projection))
            quote = "甲地隶乙郡。"
            place_fact = fact(
                "pf_001", phase_ref="ph_001", dimension="administration",
                value="乙郡", operation="attest", anchors=[{
                    "anchor_id": "anc_" + _sha256(quote)[:16], "quote": quote,
                    "quote_sha256": _sha256(quote), "revision_id": str(ctx["revision_id"]),
                    "chapter_id": ctx["chapter_id"],
                }],
            )
            place_fact.update(
                person_ref={"kind": "entity", "ref": "ent_place"}, person_key="ent_place",
                chapter_id=ctx["chapter_id"], revision_id=str(ctx["revision_id"]),
                chapter_publication_id=str(ctx["publication_id"]), source_title="synthetic",
            )
            manifest = R.build_person_state_manifest(
                projection=projection, catalog=catalog, bundle_label=label,
                stream_id=stream_id, revision_id=ctx["revision_id"],
                chapter_publication_ids=[str(ctx["publication_id"])],
                publication_by_chapter={ctx["chapter_id"]: str(ctx["publication_id"])},
                evidence={
                    "phases": [{"phase_id": "ph_001", "label": "同一阶段", "chapter_id": ctx["chapter_id"]}],
                    "phase_orders": [], "facts": [place_fact], "continuities": [], "disagreements": [],
                    "unit_phases": [
                        {"block_id": block["block_id"], "mode": "single", "phase_refs": ["ph_001"]}
                        for block in ctx["blocks"]
                    ],
                },
                assessments={"pf_001": "supported"}, assessment_hashes=[],
            )
            manifest_sha = store.persist_person_state_manifest(conn, manifest)
            self.assertEqual(manifest_sha, store.persist_person_state_manifest(conn, manifest))
            pages = [store.list_unit_places(
                conn, stream_id=stream_id, unit_id=unit["unit_id"], catalog_sha=catalog_sha,
            ) for unit in projection["units"]]
            self.assertEqual([1, 0], [len(page["places"]) for page in pages])
            self.assertEqual(0, conn.execute("SELECT count(*) FROM chronicle.person_state_unit_people").fetchone()[0])
            evidence_page = store.list_place_state_item_evidence(
                conn, stream_id=stream_id, unit_id=projection["units"][0]["unit_id"],
                place_id=place_id, item_id=pages[0]["places"][0]["item_id"], catalog_sha=catalog_sha,
            )
            self.assertEqual([quote], [entry["quote"] for entry in evidence_page["descriptors"]])

    def test_unreadable_place_evidence_rejected_before_any_state_write(self) -> None:
        with self._connect_ready() as conn:
            catalog_sha = self._seed_catalog(conn, tag="place_budget")
            ctx, stream_id = self._setup_stream(
                conn, label="place_budget", blocks=["甲地"], catalog_sha=catalog_sha,
            )
            item = self._place_item(ctx, "ent_place", fact_ref="pf_950")
            # Single oversized quote, combined first batch, page-envelope
            # overhead, and an oversized later descriptor must all fail.
            for lengths in ([22000], [12000, 12000], [21200], [10] * 16 + [22000]):
                with self.subTest(lengths=lengths):
                    descriptors = []
                    for index, length in enumerate(lengths):
                        descriptor = self._descriptor(ctx, index)
                        descriptor.update(quote="甲" * length, quote_sha256=_sha256("甲" * length))
                        descriptors.append(descriptor)
                    manifest = self._manifest(
                        ctx, stream_id, catalog_sha, assessment_hashes=[], units=[self._unit(
                            ctx, unit_id="ru_place_budget_0", unit_ordinal=0, people=[], places=[item],
                            place_evidence=[{"item_id": item["item_id"], "descriptors": descriptors}],
                        )],
                    )
                    with self.assertRaisesRegex(PersistenceError, "compiled_item_max_bytes|evidence_max_bytes"):
                        store.persist_person_state_manifest(conn, manifest)
                    for table in ("person_state_manifests", "person_state_unit_places",
                                  "person_state_place_items", "person_state_place_item_evidence"):
                        self.assertEqual(0, conn.execute(f"SELECT count(*) FROM chronicle.{table}").fetchone()[0])

    def test_manifest_replay_idempotent_and_conflict(self) -> None:
        with self._connect_ready() as conn:
            catalog_sha = self._seed_catalog(conn, tag="c1")
            ctx, stream_id = self._setup_stream(
                conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=catalog_sha
            )
            assessment_sha = self._assessment(conn, catalog_sha)
            person_id = _uuid7()
            unit_id = "ru_zhou_0"
            manifest = self._manifest(
                ctx,
                stream_id,
                catalog_sha,
                assessment_hashes=[assessment_sha],
                units=[
                    self._unit(
                        ctx,
                        unit_id=unit_id,
                        unit_ordinal=0,
                        people=[self._person(person_id, "周瑜", items=[self._item(ctx, person_id, fact_ref="pf_001")])],
                    )
                ],
            )
            first = store.persist_person_state_manifest(conn, manifest)
            second = store.persist_person_state_manifest(conn, manifest)
            self.assertEqual(first, second)
            count = conn.execute(
                "SELECT count(*) FROM chronicle.person_state_manifests"
            ).fetchone()[0]
            self.assertEqual(count, 1)

            conflicting = json.loads(json.dumps(manifest))
            conflicting["units"][0]["people"][0]["items"][0]["value"] = "另一個官職"
            with self.assertRaises(PersistenceConflict):
                store.persist_person_state_manifest(conn, conflicting)

    def test_assessment_replay_idempotent_and_conflict(self) -> None:
        with self._connect_ready() as conn:
            catalog_sha = self._seed_catalog(conn, tag="c1")
            plan = _sha256("plan-x")
            payload = {"plan_fingerprint": plan, "decisions": [{"candidate_id": "c", "assessment": "supported"}]}
            first = store.persist_person_state_assessments(
                conn,
                {
                    "plan_fingerprint": plan,
                    "base_catalog_sha": catalog_sha,
                    "compiler_version": "v1",
                    "payload": payload,
                },
            )
            second = store.persist_person_state_assessments(
                conn,
                {
                    "plan_fingerprint": plan,
                    "base_catalog_sha": catalog_sha,
                    "compiler_version": "v1",
                    "payload": payload,
                },
            )
            self.assertEqual(first, second)
            with self.assertRaises(PersistenceConflict):
                store.persist_person_state_assessments(
                    conn,
                    {
                        "plan_fingerprint": plan,
                        "base_catalog_sha": catalog_sha,
                        "compiler_version": "v1",
                        "payload": {"plan_fingerprint": plan, "decisions": []},
                    },
                )

    def test_disagreement_replay_idempotent_and_conflict(self) -> None:
        with self._connect_ready() as conn:
            catalog_sha = self._seed_catalog(conn, tag="c1")
            ctx, _stream = self._setup_stream(
                conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=catalog_sha
            )
            entry = self._disagreement_entry(ctx, fact_refs=["pf_001", "pf_002"], topic="同名")
            first = store.persist_person_state_disagreements(
                conn, self._disagreements(catalog_sha, [entry])
            )
            second = store.persist_person_state_disagreements(
                conn, self._disagreements(catalog_sha, [entry])
            )
            self.assertEqual(first, second)
            changed = json.loads(json.dumps(entry))
            changed["topic"] = "另一主题"
            with self.assertRaises(PersistenceConflict):
                store.persist_person_state_disagreements(
                    conn, self._disagreements(catalog_sha, [changed])
                )

    # -- transaction boundary ----------------------------------------------

    def test_outer_transaction_rollback_leaves_no_residue(self) -> None:
        with self._connect_ready() as conn:
            catalog_sha = self._seed_catalog(conn, tag="c1")
            ctx, stream_id = self._setup_stream(
                conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=catalog_sha
            )
            person_id = _uuid7()
            entry = self._disagreement_entry(ctx, fact_refs=["pf_001", "pf_002"], topic="同名")
            try:
                with conn.transaction():
                    assessment_sha = self._assessment(conn, catalog_sha)
                    store.persist_person_state_manifest(
                        conn,
                        self._manifest(
                            ctx,
                            stream_id,
                            catalog_sha,
                            assessment_hashes=[assessment_sha],
                            units=[
                                self._unit(
                                    ctx,
                                    unit_id="ru_zhou_0",
                                    unit_ordinal=0,
                                    people=[
                                        self._person(
                                            person_id,
                                            "周瑜",
                                            items=[self._item(ctx, person_id, fact_ref="pf_001")],
                                        )
                                    ],
                                )
                            ],
                        ),
                    )
                    store.persist_person_state_disagreements(
                        conn, self._disagreements(catalog_sha, [entry])
                    )
                    raise RuntimeError("force rollback")
            except RuntimeError:
                pass
            for table in PERSON_STATE_TABLES:
                count = conn.execute(f"SELECT count(*) FROM chronicle.{table}").fetchone()[0]
                self.assertEqual(count, 0, f"{table} kept rows after rollback")

    # -- foreign keys / missing parents ------------------------------------

    def test_cross_stream_unit_rejected(self) -> None:
        with self._connect_ready() as conn:
            catalog_sha = self._seed_catalog(conn, tag="c1")
            ctx_a, stream_a = self._setup_stream(
                conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=catalog_sha
            )
            ctx_b, stream_b = self._setup_stream(
                conn, label="lu", blocks=["魯肅字子敬"], catalog_sha=catalog_sha
            )
            assessment_sha = self._assessment(conn, catalog_sha)
            person_id = _uuid7()
            # stream B manifest cites stream A's unit
            manifest = self._manifest(
                ctx_b,
                stream_b,
                catalog_sha,
                assessment_hashes=[assessment_sha],
                units=[
                    self._unit(
                        ctx_b,
                        unit_id="ru_zhou_0",
                        unit_ordinal=0,
                        people=[
                            self._person(
                                person_id, "周瑜", items=[self._item(ctx_b, person_id, fact_ref="pf_001")]
                            )
                        ],
                    )
                ],
            )
            with self.assertRaises(PersistenceConflict):
                store.persist_person_state_manifest(conn, manifest)

    def test_missing_parent_rejected(self) -> None:
        with self._connect_ready() as conn:
            catalog_sha = self._seed_catalog(conn, tag="c1")
            ctx, stream_id = self._setup_stream(
                conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=catalog_sha
            )
            person_id = _uuid7()
            good_units = [
                self._unit(
                    ctx,
                    unit_id="ru_zhou_0",
                    unit_ordinal=0,
                    people=[
                        self._person(
                            person_id, "周瑜", items=[self._item(ctx, person_id, fact_ref="pf_001")]
                        )
                    ],
                )
            ]
            # unknown stream
            unknown = self._manifest(
                ctx, _uuid7(), catalog_sha, assessment_hashes=[], units=good_units
            )
            with self.assertRaises(PersistenceConflict):
                store.persist_person_state_manifest(conn, unknown)
            # unpersisted assessment
            missing_assessment = self._manifest(
                ctx,
                stream_id,
                catalog_sha,
                assessment_hashes=[_sha256("never-persisted")],
                units=good_units,
            )
            with self.assertRaises(PersistenceConflict):
                store.persist_person_state_manifest(conn, missing_assessment)
            # unknown base catalog on assessment
            with self.assertRaises(PersistenceConflict):
                store.persist_person_state_assessments(
                    conn,
                    {
                        "plan_fingerprint": _sha256("plan"),
                        "base_catalog_sha": _sha256("no-such-catalog"),
                        "compiler_version": "v1",
                        "payload": {"x": 1},
                    },
                )
            # disagreement under an unknown catalog
            with self.assertRaises(PersistenceConflict):
                store.persist_person_state_disagreements(
                    conn,
                    self._disagreements(
                        _sha256("no-such-catalog"),
                        [self._disagreement_entry(ctx, fact_refs=["pf_001", "pf_002"], topic="x")],
                    ),
                )

    def test_database_fk_blocks_cross_unit_item(self) -> None:
        with self._connect_ready() as conn:
            catalog_sha = self._seed_catalog(conn, tag="c1")
            ctx, stream_id = self._setup_stream(
                conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=catalog_sha
            )
            assessment_sha = self._assessment(conn, catalog_sha)
            person_id = _uuid7()
            unit_id = "ru_zhou_0"
            store.persist_person_state_manifest(
                conn,
                self._manifest(
                    ctx,
                    stream_id,
                    catalog_sha,
                    assessment_hashes=[assessment_sha],
                    units=[
                        self._unit(
                            ctx,
                            unit_id=unit_id,
                            unit_ordinal=0,
                            people=[
                                self._person(
                                    person_id, "周瑜", items=[self._item(ctx, person_id, fact_ref="pf_001")]
                                )
                            ],
                        )
                    ],
                ),
            )
            manifest_sha = conn.execute(
                "SELECT manifest_sha FROM chronicle.person_state_manifests"
            ).fetchone()[0]
            with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                with conn.transaction():
                    conn.execute(
                        """
                        INSERT INTO chronicle.person_state_items(
                            manifest_sha, stream_id, unit_id, person_id, item_kind,
                            item_id, dimension, qualification, certainty, reason_codes,
                            reason_text, phase_ids, current, source_facts,
                            evidence_count, item_ordinal, payload
                        ) VALUES (%s, %s, %s, %s, 'identity', %s, 'office', 'ordinary',
                                  'clear', '{}', '', '{}', true, '[]', 0, 0, '{}')
                        """,
                        (manifest_sha, uuid.UUID(stream_id), unit_id, _uuid7(), "psi_" + "1" * 24),
                    )

    def test_manifest_trigger_rejects_foreign_publication(self) -> None:
        with self._connect_ready() as conn:
            catalog_sha = self._seed_catalog(conn, tag="c1")
            ctx, stream_id = self._setup_stream(
                conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=catalog_sha
            )
            revision_id = ctx["revision_id"]
            with self.assertRaises(psycopg.errors.RaiseException):
                with conn.transaction():
                    conn.execute(
                        """
                        INSERT INTO chronicle.person_state_manifests(
                            manifest_sha, stream_id, revision_id, origin_catalog_sha,
                            compiler_version, assessment_hashes,
                            chapter_publication_ids, unit_phases, manifest
                        ) VALUES (%s, %s, %s, %s, 'v1', '{}', %s, '{}', '{}')
                        """,
                        (
                            _sha256("forged-manifest"),
                            uuid.UUID(stream_id),
                            revision_id,
                            catalog_sha,
                            [_uuid7()],
                        ),
                    )

    # -- pagination --------------------------------------------------------

    def test_pagination_reaches_every_entry(self) -> None:
        with self._connect_ready() as conn:
            catalog_sha = self._seed_catalog(conn, tag="c1")
            ctx, stream_id = self._setup_stream(
                conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=catalog_sha
            )
            assessment_sha = self._assessment(conn, catalog_sha)
            unit_id = "ru_zhou_0"
            people = []
            expected_people_ids: list[str] = []
            for p in range(3):
                person_id = _uuid7()
                expected_people_ids.append(person_id)
                identities = [
                    self._item(ctx, person_id, fact_ref=f"pf_{p * 10 + i:03d}") for i in range(4)
                ]
                changes = [
                    self._change(
                        ctx,
                        person_id,
                        fact_ref=f"pf_{100 + p * 10 + i:03d}",
                        to_phase_id="ph_002",
                    )
                    for i in range(2)
                ]
                evidence = [
                    {
                        "item_id": identities[0]["item_id"],
                        "descriptors": [self._descriptor(ctx, p)],
                    }
                ]
                people.append(
                    self._person(
                        person_id,
                        f"人物{p}",
                        items=identities,
                        changes=changes,
                        evidence=evidence,
                        importance="primary" if p < 2 else "other",
                    )
                )
            store.persist_person_state_manifest(
                conn,
                self._manifest(
                    ctx,
                    stream_id,
                    catalog_sha,
                    assessment_hashes=[assessment_sha],
                    units=[self._unit(ctx, unit_id=unit_id, unit_ordinal=0, people=people)],
                ),
            )

            seen: list[str] = []
            cursor = None
            while True:
                page = store.list_unit_people(
                    conn, stream_id=stream_id, unit_id=unit_id, limit=1, cursor=cursor
                )
                seen.extend(person["person_id"] for person in page["people"])
                if not page["has_more"]:
                    break
                cursor = page["next_cursor"]
            self.assertEqual(sorted(seen), sorted(expected_people_ids))

            person_id = expected_people_ids[0]
            seen_items: list[str] = []
            cursor = None
            while True:
                page = store.list_unit_person_states(
                    conn,
                    stream_id=stream_id,
                    unit_id=unit_id,
                    person_id=person_id,
                    section="identities",
                    limit=1,
                    cursor=cursor,
                )
                seen_items.extend(item["item_id"] for item in page["items"])
                if not page["has_more"]:
                    break
                cursor = page["next_cursor"]
            self.assertEqual(len(seen_items), 4)
            self.assertEqual(len(set(seen_items)), 4)

            # evidence pages: the seeded item carries one descriptor
            evidence_page = store.list_state_item_evidence(
                conn,
                stream_id=stream_id,
                unit_id=unit_id,
                person_id=person_id,
                item_id=people[0]["items"][0]["item_id"],
                limit=1,
            )
            self.assertEqual(evidence_page["descriptor_count"], 1)
            self.assertFalse(evidence_page["has_more"])

    def test_evidence_pagination(self) -> None:
        with self._connect_ready() as conn:
            catalog_sha = self._seed_catalog(conn, tag="c1")
            ctx, stream_id = self._setup_stream(
                conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=catalog_sha
            )
            assessment_sha = self._assessment(conn, catalog_sha)
            person_id = _uuid7()
            unit_id = "ru_zhou_0"
            identities = [self._item(ctx, person_id, fact_ref="pf_001")]
            descriptors = [self._descriptor(ctx, i) for i in range(4)]
            store.persist_person_state_manifest(
                conn,
                self._manifest(
                    ctx,
                    stream_id,
                    catalog_sha,
                    assessment_hashes=[assessment_sha],
                    units=[
                        self._unit(
                            ctx,
                            unit_id=unit_id,
                            unit_ordinal=0,
                            people=[
                                self._person(
                                    person_id,
                                    "周瑜",
                                    items=identities,
                                    evidence=[
                                        {
                                            "item_id": identities[0]["item_id"],
                                            "descriptors": descriptors,
                                        }
                                    ],
                                )
                            ],
                        )
                    ],
                ),
            )
            seen: list[str] = []
            cursor = None
            while True:
                page = store.list_state_item_evidence(
                    conn,
                    stream_id=stream_id,
                    unit_id=unit_id,
                    person_id=person_id,
                    item_id=identities[0]["item_id"],
                    limit=1,
                    cursor=cursor,
                )
                seen.extend(descriptor["descriptor_id"] for descriptor in page["descriptors"])
                if not page["has_more"]:
                    break
                cursor = page["next_cursor"]
            self.assertEqual(len(seen), 4)
            self.assertEqual(len(set(seen)), 4)

    # -- catalog isolation -------------------------------------------------

    def test_snapshot_catalog_isolation(self) -> None:
        with self._connect_ready() as conn:
            catalog_one = self._seed_catalog(conn, tag="c1")
            catalog_two = self._seed_catalog(conn, tag="c2")
            ctx, stream_id = self._setup_stream(
                conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=catalog_two
            )
            assessment_sha = self._assessment(conn, catalog_two)
            person_id = _uuid7()
            unit_id = "ru_zhou_0"
            identities = [self._item(ctx, person_id, fact_ref="pf_001")]
            store.persist_person_state_manifest(
                conn,
                self._manifest(
                    ctx,
                    stream_id,
                    catalog_two,
                    assessment_hashes=[assessment_sha],
                    units=[
                        self._unit(
                            ctx,
                            unit_id=unit_id,
                            unit_ordinal=0,
                            people=[self._person(person_id, "周瑜", items=identities)],
                        )
                    ],
                ),
            )
            # A newer stream is invisible to an older snapshot catalog.
            with self.assertRaises(PersistenceError):
                store.list_unit_people(
                    conn, stream_id=stream_id, unit_id=unit_id, catalog_sha=catalog_one
                )
            # but visible under its own / later catalog.
            visible = store.list_unit_people(
                conn, stream_id=stream_id, unit_id=unit_id, catalog_sha=catalog_two
            )
            self.assertEqual(visible["people_count"], 1)

    def test_disagreement_overlay_only_for_its_catalog(self) -> None:
        with self._connect_ready() as conn:
            catalog_one = self._seed_catalog(conn, tag="c1")
            catalog_two = self._seed_catalog(conn, tag="c2")
            ctx, stream_id = self._setup_stream(
                conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=catalog_one
            )
            assessment_sha = self._assessment(conn, catalog_one)
            person_id = _uuid7()
            unit_id = "ru_zhou_0"
            identities = [self._item(ctx, person_id, fact_ref="pf_001")]
            store.persist_person_state_manifest(
                conn,
                self._manifest(
                    ctx,
                    stream_id,
                    catalog_one,
                    assessment_hashes=[assessment_sha],
                    units=[
                        self._unit(
                            ctx,
                            unit_id=unit_id,
                            unit_ordinal=0,
                            people=[self._person(person_id, "周瑜", items=identities)],
                        )
                    ],
                ),
            )
            store.persist_person_state_disagreements(
                conn,
                self._disagreements(
                    catalog_one,
                    [
                        self._disagreement_entry(
                            ctx, fact_refs=["pf_001", "pf_002"], topic="任職"
                        )
                    ],
                ),
            )
            store.persist_person_state_disagreements(
                conn,
                self._disagreements(
                    catalog_two,
                    [
                        self._disagreement_entry(
                            ctx, fact_refs=["pf_005", "pf_006"], topic="來源"
                        )
                    ],
                ),
            )

            # An omitted catalog means the origin snapshot, whose own recorded
            # disagreement is combined.
            plain = store.list_unit_person_states(
                conn,
                stream_id=stream_id,
                unit_id=unit_id,
                person_id=person_id,
                section="identities",
            )
            self.assertEqual(plain["catalog_sha"], catalog_one)
            self.assertEqual(plain["items"][0]["certainty"], "uncertain")
            self.assertIn("source_disagreement", plain["items"][0]["reason_codes"])

            c1 = store.list_unit_person_states(
                conn,
                stream_id=stream_id,
                unit_id=unit_id,
                person_id=person_id,
                section="identities",
                catalog_sha=catalog_one,
            )
            self.assertEqual(c1["items"][0]["certainty"], "uncertain")
            self.assertIn("source_disagreement", c1["items"][0]["reason_codes"])

            # A later catalog only overlays its own (non-matching) links, so the
            # same item stays clear there: exact catalog isolation.
            c2 = store.list_unit_person_states(
                conn,
                stream_id=stream_id,
                unit_id=unit_id,
                person_id=person_id,
                section="identities",
                catalog_sha=catalog_two,
            )
            self.assertEqual(c2["catalog_sha"], catalog_two)
            self.assertEqual(c2["items"][0]["certainty"], "clear")
            self.assertEqual(c2["items"][0]["reason_codes"], [])

            listed_one = store.list_catalog_disagreements(conn, catalog_sha=catalog_one)
            self.assertEqual(len(listed_one["items"]), 1)
            self.assertEqual(listed_one["items"][0]["topic"], "任職")
            listed_two = store.list_catalog_disagreements(conn, catalog_sha=catalog_two)
            self.assertEqual([item["topic"] for item in listed_two["items"]], ["來源"])

    # -- immutability ------------------------------------------------------

    def test_rows_are_immutable(self) -> None:
        with self._connect_ready() as conn:
            catalog_sha = self._seed_catalog(conn, tag="c1")
            ctx, stream_id = self._setup_stream(
                conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=catalog_sha
            )
            assessment_sha = self._assessment(conn, catalog_sha)
            person_id = _uuid7()
            store.persist_person_state_manifest(
                conn,
                self._manifest(
                    ctx,
                    stream_id,
                    catalog_sha,
                    assessment_hashes=[assessment_sha],
                    units=[
                        self._unit(
                            ctx,
                            unit_id="ru_zhou_0",
                            unit_ordinal=0,
                            people=[
                                self._person(person_id, "周瑜", items=[self._item(ctx, person_id, fact_ref="pf_001")])
                            ],
                        )
                    ],
                ),
            )
            with self.assertRaises(psycopg.errors.RaiseException):
                with conn.transaction():
                    conn.execute(
                        "UPDATE chronicle.person_state_manifests SET compiler_version = 'tampered'"
                    )
            with self.assertRaises(psycopg.errors.RaiseException):
                with conn.transaction():
                    conn.execute(
                        "DELETE FROM chronicle.person_state_unit_people"
                    )

    def test_cursor_is_scope_bound(self) -> None:
        with self._connect_ready() as conn:
            fx = self._state_fixture(conn)
            stream_id = fx["stream_id"]
            unit_id = fx["unit_id"]
            person_a = fx["person_a"]
            person_b = fx["person_b"]
            catalog_two = self._seed_catalog(conn, tag="c2")

            states = store.list_unit_person_states(
                conn,
                stream_id=stream_id,
                unit_id=unit_id,
                person_id=person_a,
                section="identities",
                limit=1,
            )
            cursor = states["next_cursor"]
            self.assertIsNotNone(cursor)
            # cross-person, cross-section, cross-phase and cross-catalog replays
            with self.assertRaises(store.PersonStateCursorError):
                store.list_unit_person_states(
                    conn,
                    stream_id=stream_id,
                    unit_id=unit_id,
                    person_id=person_b,
                    section="identities",
                    cursor=cursor,
                )
            with self.assertRaises(store.PersonStateCursorError):
                store.list_unit_person_states(
                    conn,
                    stream_id=stream_id,
                    unit_id=unit_id,
                    person_id=person_a,
                    section="changes",
                    cursor=cursor,
                )
            with self.assertRaises(store.PersonStateCursorError):
                store.list_unit_person_states(
                    conn,
                    stream_id=stream_id,
                    unit_id=unit_id,
                    person_id=person_a,
                    section="identities",
                    phase_id="ph_002",
                    cursor=cursor,
                )
            with self.assertRaises(store.PersonStateCursorError):
                store.list_unit_person_states(
                    conn,
                    stream_id=stream_id,
                    unit_id=unit_id,
                    person_id=person_a,
                    section="identities",
                    catalog_sha=catalog_two,
                    cursor=cursor,
                )

            people = store.list_unit_people(
                conn, stream_id=stream_id, unit_id=unit_id, limit=1
            )
            people_cursor = people["next_cursor"]
            self.assertIsNotNone(people_cursor)
            with self.assertRaises(store.PersonStateCursorError):
                store.list_unit_people(
                    conn,
                    stream_id=stream_id,
                    unit_id=unit_id,
                    catalog_sha=catalog_two,
                    cursor=people_cursor,
                )

            evidence = store.list_state_item_evidence(
                conn,
                stream_id=stream_id,
                unit_id=unit_id,
                person_id=person_a,
                item_id=fx["a_identities"][0]["item_id"],
                limit=1,
            )
            evidence_cursor = evidence["next_cursor"]
            self.assertIsNotNone(evidence_cursor)
            with self.assertRaises(store.PersonStateCursorError):
                store.list_state_item_evidence(
                    conn,
                    stream_id=stream_id,
                    unit_id=unit_id,
                    person_id=person_a,
                    item_id=fx["a_identities"][1]["item_id"],
                    cursor=evidence_cursor,
                )

            # malformed typed positions never reach PostgreSQL
            tampered = self._tamper_cursor(evidence_cursor, after="not-an-int")
            with self.assertRaises(store.PersonStateCursorError):
                store.list_state_item_evidence(
                    conn,
                    stream_id=stream_id,
                    unit_id=unit_id,
                    person_id=person_a,
                    item_id=fx["a_identities"][0]["item_id"],
                    cursor=tampered,
                )
            with self.assertRaises(store.PersonStateCursorError):
                store.list_unit_people(
                    conn,
                    stream_id=stream_id,
                    unit_id=unit_id,
                    cursor="not-base64!!",
                )

    def test_no_catalog_first_page_then_follow_up_with_returned_catalog(self) -> None:
        with self._connect_ready() as conn:
            fx = self._state_fixture(conn)
            stream_id = fx["stream_id"]
            unit_id = fx["unit_id"]
            origin = fx["catalog_sha"]
            person_a = fx["person_a"]
            person_b = fx["person_b"]

            # An omitted-catalog read still overlays the origin snapshot's
            # own recorded disagreements (it advertises that catalog).
            store.persist_person_state_disagreements(
                conn,
                self._disagreements(
                    origin,
                    [
                        self._disagreement_entry(
                            fx["ctx"], fact_refs=["pf_000", "pf_003"], topic="任職"
                        )
                    ],
                ),
            )

            # people: first page without a catalog, follow-up with the returned
            # catalog SHA must succeed and reach the final page.
            page = store.list_unit_people(
                conn, stream_id=stream_id, unit_id=unit_id, limit=1
            )
            self.assertEqual(page["catalog_sha"], origin)
            self.assertTrue(page["has_more"])
            seen = [person["person_id"] for person in page["people"]]
            page = store.list_unit_people(
                conn,
                stream_id=stream_id,
                unit_id=unit_id,
                catalog_sha=page["catalog_sha"],
                limit=1,
                cursor=page["next_cursor"],
            )
            self.assertEqual(page["catalog_sha"], origin)
            self.assertFalse(page["has_more"])
            seen.extend(person["person_id"] for person in page["people"])
            self.assertEqual(sorted(seen), sorted([person_a, person_b]))

            # identities: walk every page, passing the returned catalog on the
            # follow-up requests, and see the omitted-catalog overlay.
            seen_ids: list[str] = []
            cursor = None
            catalog = None
            while True:
                page = store.list_unit_person_states(
                    conn,
                    stream_id=stream_id,
                    unit_id=unit_id,
                    person_id=person_a,
                    section="identities",
                    catalog_sha=catalog,
                    limit=1,
                    cursor=cursor,
                )
                self.assertEqual(page["catalog_sha"], origin)
                seen_ids.extend(item["item_id"] for item in page["items"])
                if not page["has_more"]:
                    break
                cursor = page["next_cursor"]
                catalog = page["catalog_sha"]
            self.assertEqual(len(seen_ids), 4)
            self.assertEqual(len(set(seen_ids)), 4)

            first = store.list_unit_person_states(
                conn,
                stream_id=stream_id,
                unit_id=unit_id,
                person_id=person_a,
                section="identities",
                limit=1,
            )
            self.assertEqual(first["items"][0]["certainty"], "uncertain")
            self.assertIn("source_disagreement", first["items"][0]["reason_codes"])

            # evidence: same first-page-without-catalog then returned-catalog
            # follow-up flow.
            item_id = fx["a_identities"][0]["item_id"]
            seen_descriptors: list[str] = []
            cursor = None
            catalog = None
            while True:
                page = store.list_state_item_evidence(
                    conn,
                    stream_id=stream_id,
                    unit_id=unit_id,
                    person_id=person_a,
                    item_id=item_id,
                    catalog_sha=catalog,
                    limit=1,
                    cursor=cursor,
                )
                self.assertEqual(page["catalog_sha"], origin)
                seen_descriptors.extend(
                    descriptor["descriptor_id"] for descriptor in page["descriptors"]
                )
                if not page["has_more"]:
                    break
                cursor = page["next_cursor"]
                catalog = page["catalog_sha"]
            self.assertEqual(len(seen_descriptors), 4)
            self.assertEqual(len(set(seen_descriptors)), 4)

    def test_person_and_phase_membership_with_catalog(self) -> None:
        with self._connect_ready() as conn:
            fx = self._state_fixture(conn)
            stream_id = fx["stream_id"]
            unit_id = fx["unit_id"]
            catalog_sha = fx["catalog_sha"]

            # unknown person is an error even when a catalog is supplied
            with self.assertRaises(PersistenceError):
                store.list_unit_person_states(
                    conn,
                    stream_id=stream_id,
                    unit_id=unit_id,
                    person_id=_uuid7(),
                    section="identities",
                    catalog_sha=catalog_sha,
                )
            # a phase that is not bound to the unit is an error, not an empty page
            with self.assertRaises(PersistenceError):
                store.list_unit_person_states(
                    conn,
                    stream_id=stream_id,
                    unit_id=unit_id,
                    person_id=fx["person_a"],
                    section="identities",
                    phase_id="ph_099",
                    catalog_sha=catalog_sha,
                )
            with self.assertRaises(PersistenceError):
                store.list_state_item_evidence(
                    conn,
                    stream_id=stream_id,
                    unit_id=unit_id,
                    person_id=fx["person_a"],
                    item_id=fx["a_identities"][0]["item_id"],
                    phase_id="ph_099",
                    catalog_sha=catalog_sha,
                )
            # malformed item ids are rejected before touching the database
            with self.assertRaises(PersistenceError):
                store.list_state_item_evidence(
                    conn,
                    stream_id=stream_id,
                    unit_id=unit_id,
                    person_id=fx["person_a"],
                    item_id="not-an-item-id",
                )

    def test_list_catalog_disagreements_requires_known_catalog(self) -> None:
        with self._connect_ready() as conn:
            with self.assertRaises(PersistenceError):
                store.list_catalog_disagreements(conn, catalog_sha=_sha256("no-such-catalog"))
            catalog_sha = self._seed_catalog(conn, tag="c1")
            page = store.list_catalog_disagreements(conn, catalog_sha=catalog_sha)
            self.assertEqual(page["items"], [])

    def test_disagreement_cursor_is_catalog_bound(self) -> None:
        with self._connect_ready() as conn:
            catalog_one = self._seed_catalog(conn, tag="c1")
            catalog_two = self._seed_catalog(conn, tag="c2")
            ctx, _stream = self._setup_stream(
                conn, label="zhou", blocks=["瑜字公瑾"], catalog_sha=catalog_one
            )
            store.persist_person_state_disagreements(
                conn,
                self._disagreements(
                    catalog_one,
                    [
                        self._disagreement_entry(
                            ctx, fact_refs=["pf_001", "pf_002"], topic="A"
                        ),
                        self._disagreement_entry(
                            ctx, fact_refs=["pf_003", "pf_004"], topic="B"
                        ),
                    ],
                ),
            )
            store.persist_person_state_disagreements(
                conn,
                self._disagreements(
                    catalog_two,
                    [self._disagreement_entry(ctx, fact_refs=["pf_001", "pf_002"], topic="A")],
                ),
            )
            page = store.list_catalog_disagreements(
                conn, catalog_sha=catalog_one, limit=1
            )
            cursor = page["next_cursor"]
            self.assertIsNotNone(cursor)
            with self.assertRaises(store.PersonStateCursorError):
                store.list_catalog_disagreements(
                    conn, catalog_sha=catalog_two, cursor=cursor
                )
            with self.assertRaises(store.PersonStateCursorError):
                store.list_catalog_disagreements(
                    conn, catalog_sha=catalog_one, cursor="garbage"
                )

    def test_reason_text_matches_shared_contract(self) -> None:
        for code in P.REASON_CODES:
            self.assertEqual(store._reason_text([code]), P._reason_text([code]))


if __name__ == "__main__":
    unittest.main()
