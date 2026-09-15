"""PostgreSQL integration tests for background candidate and binding authority."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest import mock

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from PIL import Image

import background_assets as backgrounds
from migrations import apply_migrations
from test_postgres_v0 import _control_url


def _database_conninfo(control_url: str, database_name: str) -> str:
    params = conninfo_to_dict(control_url)
    params["dbname"] = database_name
    return make_conninfo(**params)


def _image(color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (4, 3), color).save(output, format="PNG")
    return output.getvalue()


def _paragraph_id(ordinal: int) -> str:
    return f"hp_{ordinal:024x}"


def _phase_id(ordinal: int) -> str:
    return f"hphase_{ordinal:024x}"


def _seed_edition(conn, version: str, paragraph_count: int = 4) -> list[str]:
    paragraph_ids = [_paragraph_id(index) for index in range(paragraph_count)]
    with conn.transaction():
        conn.execute(
            """
            INSERT INTO chronicle.history_editions(
                edition_version, manifest_sha256, content_sha256,
                fragment_count, paragraph_count, manifest, metadata
            ) VALUES (%s, %s, %s, 1, %s, %s, %s)
            """,
            (version, version, version, paragraph_count, Jsonb({}), Jsonb({})),
        )
        for ordinal, paragraph_id in enumerate(paragraph_ids):
            conn.execute(
                """
                INSERT INTO chronicle.history_edition_paragraph_index(
                    edition_version, ordinal, paragraph_id, fragment_version,
                    source_paragraph_id, source_ordinal, phase_id,
                    conclusion_ids, content_ref
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    version,
                    ordinal,
                    paragraph_id,
                    "c" * 64,
                    f"source-{ordinal}",
                    ordinal,
                    _phase_id(ordinal),
                    Jsonb([]),
                    Jsonb({}),
                ),
            )
    return paragraph_ids


class BackgroundAssetsPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_background_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        self.database_url = _database_conninfo(self.control_url, self.database_name)
        self.storage = tempfile.TemporaryDirectory(prefix="chronicle-background-")
        self.storage_dir = Path(self.storage.name)
        with psycopg.connect(self.database_url) as conn:
            apply_migrations(conn)
            self.first_edition = "a" * 64
            self.second_edition = "b" * 64
            self.paragraphs = _seed_edition(conn, self.first_edition)
            self.second_paragraphs = _seed_edition(conn, self.second_edition)

    def tearDown(self) -> None:
        self.storage.cleanup()
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.database_name))
            )

    def _connect(self):
        return psycopg.connect(self.database_url)

    def _asset(
        self,
        conn,
        color: tuple[int, int, int],
        *,
        source: str = "operator-upload",
        era: str = "late Han",
        prompt: str = "a quiet river",
    ) -> dict:
        return backgrounds.create_asset(
            conn,
            data=_image(color),
            storage_dir=self.storage_dir,
            filename="scene.png",
            content_type="image/png",
            source=source,
            era=era,
            prompt=prompt,
            metadata={"license": "internal"},
        )

    def test_candidate_is_private_until_saved_and_disable_is_independent(self) -> None:
        with self._connect() as conn:
            asset = self._asset(conn, (100, 80, 40))
            media, raw = backgrounds.read_candidate_asset(
                conn,
                storage_dir=self.storage_dir,
                asset_id=asset["asset_id"],
            )
            self.assertEqual(media, "image/png")
            self.assertEqual(raw, _image((100, 80, 40)))

            with self.assertRaises(backgrounds.BackgroundNotFound):
                backgrounds.read_public_asset(
                    conn,
                    storage_dir=self.storage_dir,
                    asset_id=asset["asset_id"],
                    edition_version=self.first_edition,
                    paragraph_id=self.paragraphs[0],
                )

            first = backgrounds.create_binding(
                conn,
                storage_dir=self.storage_dir,
                edition_version=self.first_edition,
                start_paragraph_id=self.paragraphs[0],
                end_paragraph_id=self.paragraphs[1],
                asset_id=asset["asset_id"],
                asset_version_id=asset["asset_version_id"],
                display={"opacity": 0.5, "position": {"x": 0.25, "y": 0.75}},
                actor="operator",
            )
            second = backgrounds.create_binding(
                conn,
                storage_dir=self.storage_dir,
                edition_version=self.first_edition,
                start_paragraph_id=self.paragraphs[2],
                end_paragraph_id=self.paragraphs[2],
                asset_id=asset["asset_id"],
                asset_version_id=asset["asset_version_id"],
                actor="operator",
            )
            self.assertNotEqual(first["binding_id"], second["binding_id"])

            public = backgrounds.read_public_binding(
                conn,
                edition_version=self.first_edition,
                paragraph_id=self.paragraphs[0],
            )
            assert public is not None
            self.assertEqual(public["binding_id"], first["binding_id"])
            self.assertNotIn("prompt", public["asset"])
            media, raw, locator = backgrounds.read_public_asset(
                conn,
                storage_dir=self.storage_dir,
                asset_id=asset["asset_id"],
                edition_version=self.first_edition,
                paragraph_id=self.paragraphs[0],
            )
            self.assertEqual((media, raw), ("image/png", _image((100, 80, 40))))
            self.assertEqual(locator["binding_id"], first["binding_id"])

            # A new sidecar connection sees the same immutable asset version,
            # binding and file bytes; no in-process cache is part of the read.
            conn.commit()
            with self._connect() as restarted:
                persisted = backgrounds.get_asset(
                    restarted,
                    asset["asset_id"],
                    storage_dir=self.storage_dir,
                )
                self.assertEqual(persisted["asset_version_id"], asset["asset_version_id"])
                media, raw, _ = backgrounds.read_public_asset(
                    restarted,
                    storage_dir=self.storage_dir,
                    asset_id=asset["asset_id"],
                    edition_version=self.first_edition,
                    paragraph_id=self.paragraphs[0],
                )
                self.assertEqual((media, raw), ("image/png", _image((100, 80, 40))))

            backgrounds.disable_binding(conn, first["binding_id"], actor="operator")
            self.assertIsNone(
                backgrounds.read_public_binding(
                    conn,
                    edition_version=self.first_edition,
                    paragraph_id=self.paragraphs[0],
                )
            )
            with self.assertRaises(backgrounds.BackgroundNotFound):
                backgrounds.read_public_asset(
                    conn,
                    storage_dir=self.storage_dir,
                    asset_id=asset["asset_id"],
                    edition_version=self.first_edition,
                    paragraph_id=self.paragraphs[0],
                )
            self.assertIsNotNone(
                backgrounds.read_public_binding(
                    conn,
                    edition_version=self.first_edition,
                    paragraph_id=self.paragraphs[2],
                )
            )
            audit = backgrounds.list_binding_audit(conn, first["binding_id"])
            self.assertEqual([entry["action"] for entry in audit["entries"]], ["created", "disabled"])

    def test_save_rejects_wrong_ranges_versions_and_overlaps(self) -> None:
        with self._connect() as conn:
            asset = self._asset(conn, (10, 20, 30))
            other = self._asset(conn, (30, 20, 10))
            backgrounds.create_binding(
                conn,
                storage_dir=self.storage_dir,
                edition_version=self.first_edition,
                start_paragraph_id=self.paragraphs[0],
                end_paragraph_id=self.paragraphs[1],
                asset_id=asset["asset_id"],
                asset_version_id=asset["asset_version_id"],
            )
            with self.assertRaises(backgrounds.BackgroundConflict) as error:
                backgrounds.create_binding(
                    conn,
                    storage_dir=self.storage_dir,
                    edition_version=self.first_edition,
                    start_paragraph_id=self.paragraphs[1],
                    end_paragraph_id=self.paragraphs[2],
                    asset_id=other["asset_id"],
                    asset_version_id=other["asset_version_id"],
                )
            self.assertEqual(error.exception.code, "overlap_conflict")

            with self.assertRaises(backgrounds.BackgroundValidationError) as error:
                backgrounds.create_binding(
                    conn,
                    storage_dir=self.storage_dir,
                    edition_version=self.first_edition,
                    start_paragraph_id=self.paragraphs[0],
                    end_paragraph_id="hp_ffffffffffffffffffffffff",
                    asset_id=other["asset_id"],
                    asset_version_id=other["asset_version_id"],
                )
            self.assertEqual(error.exception.code, "unknown_paragraph")

            with self.assertRaises(backgrounds.BackgroundValidationError) as error:
                backgrounds.create_binding(
                    conn,
                    storage_dir=self.storage_dir,
                    edition_version=self.first_edition,
                    start_paragraph_id=self.paragraphs[2],
                    end_paragraph_id=self.paragraphs[2],
                    asset_id=asset["asset_id"],
                    asset_version_id=other["asset_version_id"],
                )
            self.assertEqual(error.exception.code, "asset_version_mismatch")

            with self.assertRaises(backgrounds.BackgroundValidationError) as error:
                backgrounds.create_binding(
                    conn,
                    storage_dir=self.storage_dir,
                    edition_version="c" * 64,
                    start_paragraph_id=self.paragraphs[2],
                    end_paragraph_id=self.paragraphs[2],
                    asset_id=asset["asset_id"],
                    asset_version_id=asset["asset_version_id"],
                )
            self.assertEqual(error.exception.code, "unknown_edition")

            active = conn.execute(
                "SELECT count(*) FROM chronicle.background_bindings WHERE status = 'active'"
            ).fetchone()[0]
            self.assertEqual(active, 1)

    def test_replace_is_explicit_and_new_edition_does_not_inherit_coordinates(self) -> None:
        with self._connect() as conn:
            first_asset = self._asset(conn, (1, 2, 3))
            second_asset = self._asset(
                conn,
                (4, 5, 6),
                source="archive-upload",
                era="Republic era",
                prompt="a quiet modern street",
            )
            new_version = backgrounds.create_asset_version(
                conn,
                first_asset["asset_id"],
                data=_image((9, 9, 9)),
                storage_dir=self.storage_dir,
                filename="scene-v2.png",
                content_type="image/png",
            )
            self.assertEqual(new_version["asset_id"], first_asset["asset_id"])
            self.assertEqual(new_version["version"], 2)
            binding = backgrounds.create_binding(
                conn,
                storage_dir=self.storage_dir,
                edition_version=self.first_edition,
                start_paragraph_id=self.paragraphs[0],
                end_paragraph_id=self.paragraphs[0],
                asset_id=first_asset["asset_id"],
                asset_version_id=first_asset["asset_version_id"],
                actor="first",
            )
            self.assertIsNone(
                backgrounds.read_public_binding(
                    conn,
                    edition_version=self.second_edition,
                    paragraph_id=self.second_paragraphs[0],
                )
            )
            replaced = backgrounds.replace_binding(
                conn,
                binding["binding_id"],
                storage_dir=self.storage_dir,
                asset_id=second_asset["asset_id"],
                asset_version_id=second_asset["asset_version_id"],
                display={"scale": 1.5},
                expected_revision=1,
                actor="second",
            )
            self.assertEqual(replaced["revision"], 2)
            self.assertEqual(replaced["asset_id"], second_asset["asset_id"])
            self.assertEqual(replaced["asset"]["era"], "Republic era")
            with self.assertRaises(backgrounds.BackgroundConflict):
                backgrounds.replace_binding(
                    conn,
                    binding["binding_id"],
                    storage_dir=self.storage_dir,
                    asset_id=first_asset["asset_id"],
                    asset_version_id=first_asset["asset_version_id"],
                    expected_revision=1,
                )
            audit = backgrounds.list_binding_audit(conn, binding["binding_id"])
            self.assertEqual([entry["action"] for entry in audit["entries"]], ["created", "replaced"])

            second_binding = backgrounds.create_binding(
                conn,
                storage_dir=self.storage_dir,
                edition_version=self.second_edition,
                start_paragraph_id=self.second_paragraphs[0],
                end_paragraph_id=self.second_paragraphs[0],
                asset_id=first_asset["asset_id"],
                asset_version_id=first_asset["asset_version_id"],
            )
            self.assertEqual(second_binding["edition_version"], self.second_edition)
            self.assertEqual(
                backgrounds.read_public_binding(
                    conn,
                    edition_version=self.second_edition,
                    paragraph_id=self.second_paragraphs[0],
                )["binding_id"],
                second_binding["binding_id"],
            )

    def test_registration_failure_removes_the_new_file(self) -> None:
        with self._connect() as conn:
            existing = self._asset(conn, (7, 8, 9))
            before = sorted(path for path in self.storage_dir.rglob("*") if path.is_file())
            with mock.patch.object(
                backgrounds,
                "new_uuid7",
                side_effect=[uuid.UUID(existing["asset_id"]), uuid.uuid4()],
            ):
                with self.assertRaises(psycopg.errors.UniqueViolation):
                    self._asset(conn, (9, 8, 7))
            after = sorted(path for path in self.storage_dir.rglob("*") if path.is_file())
            self.assertEqual(after, before)
            self.assertEqual(
                conn.execute("SELECT count(*) FROM chronicle.background_assets").fetchone()[0],
                1,
            )


if __name__ == "__main__":
    unittest.main()
