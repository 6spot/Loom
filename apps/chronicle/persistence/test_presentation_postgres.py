"""PostgreSQL 18 contracts for Chronicle C1-T12 Reader Presentation."""

from __future__ import annotations

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
INGESTION = HERE.parent / "ingestion" / "prototype"
for candidate in (str(HERE), str(INGESTION)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import canonical_store  # noqa: E402
import presentation  # noqa: E402
import staged_store  # noqa: E402
from common import PersistenceError  # noqa: E402
from migrations import apply_migrations  # noqa: E402

import publication_v0  # noqa: E402

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


def _meta() -> dict:
    return {"method": "model", "job_id": "c1t12", "confidence": 0.9}


def _bundle() -> dict:
    return {
        "schema_version": "0.1",
        "source": {
            "temp_id": "src_001",
            "kind": "source",
            "source_type": "book",
            "title": "三國志·武帝紀",
            "author": "陳壽",
            "language": "lzh",
            "extraction": _meta(),
        },
        "entities": [
            {
                "temp_id": "ent_001",
                "kind": "entity",
                "type": "person",
                "canonical_name": "曹操",
                "aliases": ["魏武"],
                "mentions": [{"text": "公"}],
                "resolution": {"status": "unresolved"},
                "extraction": _meta(),
            }
        ],
        "events": [
            {
                "temp_id": "evt_001",
                "kind": "event",
                "type": "battle",
                "title": "赤壁交战",
                "time": {
                    "original_text": "建安十三年",
                    "source_calendar": {"system": "chinese_lunisolar_regnal", "era": "建安", "era_year": 13, "season": None, "month": None, "inherited_fields": []},
                    "normalized": {"calendar": "proleptic_gregorian", "year": 208, "month": None, "day": None, "precision": "year", "conversion_status": "year_only"},
                },
                "participants": [{"entity_ref": "ent_001", "role": "commander"}],
                "places": [],
                "extraction": _meta(),
            }
        ],
        "claims": [
            {
                "temp_id": "clm_ent_001",
                "kind": "claim",
                "subject": {"kind": "entity_ref", "ref": "ent_001"},
                "predicate": "advanced_south",
                "object": None,
                "time": None,
                "evidence": {
                    "text": "公至赤壁。",
                    "source_ref": "src_001",
                    "locator": {"work": "三國志", "section": "武帝紀"},
                },
                "assessment": {"status": "unassessed"},
                "extraction": _meta(),
            },
            {
                "temp_id": "clm_evt_001",
                "kind": "claim",
                "subject": {"kind": "event_ref", "ref": "evt_001"},
                "predicate": "outcome",
                "object": None,
                "time": None,
                "evidence": {
                    "text": "與備戰，不利。",
                    "source_ref": "src_001",
                    "locator": {"work": "三國志", "section": "武帝紀"},
                },
                "assessment": {"status": "unassessed"},
                "extraction": _meta(),
            },
        ],
        "warnings": [],
    }


class FakePresentationModel:
    name = "reader-test-model-v1"

    def __init__(self, *, target_kind: str, canonical_id: str, text: str, claim_ref: str):
        self.target_kind = target_kind
        self.canonical_id = canonical_id
        self.text = text
        self.claim_ref = claim_ref
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(
            {
                "schema": "chronicle.reader-presentation",
                "version": "0.1",
                "target_kind": self.target_kind,
                "canonical_id": self.canonical_id,
                "language": "zh-CN",
                "blocks": [
                    {
                        "block_kind": "overview" if self.target_kind == "entity" else "outcome",
                        "epistemic_mode": "fact_summary",
                        "text": self.text,
                        "claim_refs": [{"bundle": "wudi", "ref": self.claim_ref}],
                    }
                ],
            },
            ensure_ascii=False,
        )


class ReaderPresentationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_c1t12_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        self.database_url = _database_conninfo(self.control_url, self.database_name)
        with psycopg.connect(self.database_url) as conn:
            apply_migrations(conn)
            bundle = _bundle()
            staged_store.persist_bundle(conn, "wudi", bundle)
            catalog = publication_v0.publish_catalog({"wudi": bundle}, [], None)
            canonical_store.persist_catalog(conn, catalog)
            conn.commit()
            self.entity_id = next(
                row["canonical_id"]
                for row in catalog["canonical_entities"]
                if row["representations"] == [{"bundle": "wudi", "ref": "ent_001"}]
            )
            self.event_id = next(
                row["canonical_id"]
                for row in catalog["canonical_events"]
                if row["representations"] == [{"bundle": "wudi", "ref": "evt_001"}]
            )

    def tearDown(self) -> None:
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name))
            )

    def test_event_and_entity_presentations_are_claim_bound_and_versioned(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            before_claim = conn.execute(
                "SELECT payload FROM chronicle.staged_claims WHERE bundle_label='wudi' AND record_ref='clm_evt_001'"
            ).fetchone()[0]
            event_context = presentation.load_generation_context(
                conn, target_kind="event", canonical_id=self.event_id
            )
        model = FakePresentationModel(
            target_kind="event",
            canonical_id=self.event_id,
            text="曹操一方在赤壁与刘备方面交战，战事不利。",
            claim_ref="clm_evt_001",
        )
        candidate = presentation.generate_candidate(event_context, model)
        self.assertIn("INPUT:", model.prompts[0])
        self.assertIn("不得补充", model.prompts[0])
        with psycopg.connect(self.database_url) as conn:
            first = presentation.persist_candidate(
                conn,
                context=event_context,
                candidate=candidate,
                model_version=model.name,
            )
            conn.commit()
            self.assertEqual(first["presentation_version"], 1)
            support = conn.execute(
                """
                SELECT s.bundle_label, s.claim_ref, c.payload->'evidence'->>'text'
                FROM chronicle.reader_presentation_supports s
                JOIN chronicle.staged_claims c
                  ON c.bundle_label=s.bundle_label AND c.record_ref=s.claim_ref
                WHERE s.presentation_id=%s
                """,
                (uuid.UUID(first["presentation_id"]),),
            ).fetchall()
            self.assertEqual(support, [("wudi", "clm_evt_001", "與備戰，不利。")])

        # Same context + changed reader prose is a new projection version, not
        # a mutation of the canonical Event or source Claim.
        model2 = FakePresentationModel(
            target_kind="event",
            canonical_id=self.event_id,
            text="史料记载，曹操在赤壁与刘备一方交战，此战对曹操不利。",
            claim_ref="clm_evt_001",
        )
        candidate2 = presentation.generate_candidate(event_context, model2)
        with psycopg.connect(self.database_url) as conn:
            second = presentation.persist_candidate(
                conn,
                context=event_context,
                candidate=candidate2,
                model_version=model2.name,
            )
            conn.commit()
            self.assertEqual(second["presentation_version"], 2)
            self.assertNotEqual(first["presentation_id"], second["presentation_id"])
            lineage = conn.execute(
                "SELECT supersedes_presentation_id FROM chronicle.reader_presentations WHERE presentation_id=%s",
                (uuid.UUID(second["presentation_id"]),),
            ).fetchone()[0]
            self.assertEqual(str(lineage), first["presentation_id"])
            after_claim = conn.execute(
                "SELECT payload FROM chronicle.staged_claims WHERE bundle_label='wudi' AND record_ref='clm_evt_001'"
            ).fetchone()[0]
            self.assertEqual(after_claim, before_claim)
            canonical_still_exists = conn.execute(
                "SELECT canonical_id::text FROM chronicle.canonical_events WHERE canonical_id=%s",
                (uuid.UUID(self.event_id),),
            ).fetchone()[0]
            self.assertEqual(canonical_still_exists, self.event_id)

            entity_context = presentation.load_generation_context(
                conn, target_kind="entity", canonical_id=self.entity_id
            )
        entity_model = FakePresentationModel(
            target_kind="entity",
            canonical_id=self.entity_id,
            text="史料记载曹操行军至赤壁。",
            claim_ref="clm_ent_001",
        )
        entity_candidate = presentation.generate_candidate(entity_context, entity_model)
        with psycopg.connect(self.database_url) as conn:
            stored = presentation.persist_candidate(
                conn,
                context=entity_context,
                candidate=entity_candidate,
                model_version=entity_model.name,
            )
            conn.commit()
            self.assertEqual(stored["presentation_version"], 1)

    def test_same_input_and_content_is_idempotently_adopted(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            context = presentation.load_generation_context(
                conn, target_kind="event", canonical_id=self.event_id
            )
        model = FakePresentationModel(
            target_kind="event",
            canonical_id=self.event_id,
            text="曹操在赤壁交战，战事不利。",
            claim_ref="clm_evt_001",
        )
        candidate = presentation.generate_candidate(context, model)
        with psycopg.connect(self.database_url) as conn:
            first = presentation.persist_candidate(
                conn, context=context, candidate=candidate, model_version=model.name
            )
            conn.commit()
        with psycopg.connect(self.database_url) as conn:
            second = presentation.persist_candidate(
                conn, context=context, candidate=candidate, model_version=model.name
            )
            conn.commit()
            count = conn.execute("SELECT count(*) FROM chronicle.reader_presentations").fetchone()[0]
        self.assertFalse(first["adopted"])
        self.assertTrue(second["adopted"])
        self.assertEqual(first["presentation_id"], second["presentation_id"])
        self.assertEqual(count, 1)

    def test_unknown_claim_or_language_fails_closed(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            context = presentation.load_generation_context(
                conn, target_kind="event", canonical_id=self.event_id
            )
        base = {
            "schema": "chronicle.reader-presentation",
            "version": "0.1",
            "target_kind": "event",
            "canonical_id": self.event_id,
            "language": "zh-CN",
            "blocks": [
                {
                    "block_kind": "outcome",
                    "epistemic_mode": "fact_summary",
                    "text": "这句话没有 Chronicle Claim 支持。",
                    "claim_refs": [{"bundle": "wudi", "ref": "clm_missing"}],
                }
            ],
        }
        with self.assertRaises(PersistenceError):
            presentation.validate_candidate(base, context)
        multilingual = dict(base)
        multilingual["language"] = "en"
        multilingual["blocks"] = [
            {
                "block_kind": "outcome",
                "epistemic_mode": "fact_summary",
                "text": "Cao Cao's side fared poorly at Red Cliffs.",
                "claim_refs": [{"bundle": "wudi", "ref": "clm_evt_001"}],
            }
        ]
        with self.assertRaises(PersistenceError):
            presentation.validate_candidate(multilingual, context)

    def test_uncertainty_context_requires_explicit_uncertainty_block(self) -> None:
        context = {
            "target_kind": "event",
            "canonical_id": self.event_id,
            "representations": [
                {"claims": [{"bundle": "wudi", "ref": "clm_evt_001"}]}
            ],
            "constraints": {"requires_uncertainty": True},
        }
        candidate = {
            "schema": "chronicle.reader-presentation",
            "version": "0.1",
            "target_kind": "event",
            "canonical_id": self.event_id,
            "language": "zh-CN",
            "blocks": [
                {
                    "block_kind": "outcome",
                    "epistemic_mode": "fact_summary",
                    "text": "现有材料只支持这一条事实。",
                    "claim_refs": [{"bundle": "wudi", "ref": "clm_evt_001"}],
                }
            ],
        }
        with self.assertRaisesRegex(PersistenceError, "uncertainty"):
            presentation.validate_candidate(candidate, context)
        candidate["blocks"].append(
            {
                "block_kind": "uncertainty",
                "epistemic_mode": "uncertainty",
                "text": "现有来源仍保留一项不确定判断。",
                "claim_refs": [{"bundle": "wudi", "ref": "clm_evt_001"}],
            }
        )
        normalized = presentation.validate_candidate(candidate, context)
        self.assertEqual(normalized["blocks"][1]["block_kind"], "uncertainty")


if __name__ == "__main__":
    unittest.main()
