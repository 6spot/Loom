"""Regression tests for Chronicle staged-vs-published corpus authority.

C1-T13 exposed a batch-ingestion defect where a source bundle persisted by one
in-flight job could be pulled into another job's canonical publication before
its own review gate completed.  These tests lock the corrected boundary:
staging is durable extraction evidence, while the latest canonical catalog is
the authority for the published corpus used by cross-source resolution and
publication.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

HERE = Path(__file__).resolve().parent
PERSISTENCE = HERE.parent / "persistence"
for path in (str(HERE), str(PERSISTENCE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import canonical_store  # noqa: E402
import resolution_store  # noqa: E402
import resolve_publish as R  # noqa: E402
import staged_store  # noqa: E402
from migrations import apply_migrations  # noqa: E402

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
        cwd=HERE.parents[2],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    with psycopg.connect(url, connect_timeout=10):
        return url


def _database_conninfo(control_url: str, database_name: str) -> str:
    params = conninfo_to_dict(control_url)
    params["dbname"] = database_name
    return make_conninfo(**params)


def _bundle(title: str, person: str) -> dict:
    meta = {"method": "model", "job_id": "published-boundary-test", "confidence": 1.0}
    return {
        "schema_version": "0.1",
        "source": {
            "temp_id": "src_001",
            "kind": "source",
            "source_type": "book",
            "title": title,
            "author": "陳壽",
            "language": "lzh",
            "extraction": meta,
        },
        "entities": [
            {
                "temp_id": "ent_001",
                "kind": "entity",
                "type": "person",
                "canonical_name": person,
                "aliases": [],
                "mentions": [{"text": person}],
                "resolution": {"status": "unresolved"},
                "extraction": meta,
            }
        ],
        "events": [],
        "claims": [],
        "warnings": [],
    }


class PublishedCorpusBoundaryPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_published_boundary_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            from psycopg import sql

            conn.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name))
            )
        self.database_url = _database_conninfo(self.control_url, self.database_name)
        with psycopg.connect(self.database_url) as conn:
            apply_migrations(conn)

    def tearDown(self) -> None:
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            from psycopg import sql

            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(self.database_name)
                )
            )

    def _seed_published_and_inflight(self, conn) -> tuple[dict, dict]:
        published = _bundle("武帝紀", "曹操")
        inflight = _bundle("在途列傳", "曹操")
        staged_store.persist_bundle(conn, "published", published)
        staged_store.persist_bundle(conn, "inflight", inflight)
        catalog = R.publication_v0.publish_catalog(
            {"published": published}, [], existing_catalog=None
        )
        canonical_store.persist_catalog(conn, catalog)
        conn.commit()
        return published, inflight

    def test_staged_inflight_bundle_is_not_published_corpus_input(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            self._seed_published_and_inflight(conn)

            self.assertEqual(
                set(R.read_all_staged_bundles(conn)), {"published", "inflight"}
            )
            self.assertEqual(set(R.read_corpus_bundles(conn)), {"published"})
            self.assertEqual(
                R.published_bundle_labels(R.read_latest_catalog(conn)), {"published"}
            )

    def test_resolution_touching_inflight_bundle_is_not_published_history(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            published, inflight = self._seed_published_and_inflight(conn)
            resolutions = R.build_initial_resolutions(
                new_bundle=inflight,
                new_label="inflight",
                corpus={"published": published},
            )
            self.assertEqual(len(resolutions), 1)
            resolution_store.persist_resolution(conn, resolutions[0])
            conn.commit()

            self.assertEqual(len(R.read_all_staged_resolutions(conn)), 1)
            self.assertEqual(R.read_corpus_resolutions(conn), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
