"""Shared PostgreSQL fixtures for current staged worker integration tests."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for path in (str(HERE), str(HERE.parent / "persistence")):
    if path not in sys.path:
        sys.path.insert(0, path)

import control_plane  # noqa: E402
from migrations import apply_migrations  # noqa: E402


DEFAULT_CONTROL_URL = "postgresql://loom:loom@127.0.0.1:15432/loom_control"

TEXT_DISTINCT = """# 測試書

## 先主傳

劉備字玄德，涿郡涿縣人也。漢景帝子中山靖王勝之後也。備少孤，與母以織席販履為業。

## 周瑜傳

周瑜字公瑾，廬江舒人也。瑜長壯有姿貌，精音律，江東諺云曲有誤周郎顧。
"""


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


class CurrentPipelineDatabase:
    """Mixin with isolated database lifecycle and ordinary chapter queueing."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.control_url = _control_url()

    def setUp(self) -> None:
        self.database_name = f"chronicle_current_{uuid.uuid4().hex}"
        with psycopg.connect(self.control_url, autocommit=True) as conn:
            from psycopg import sql

            conn.execute(
                sql.SQL("CREATE DATABASE {}").format(
                    sql.Identifier(self.database_name)
                )
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

    def _queue_job(self, text: str):
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        with psycopg.connect(self.database_url) as conn:
            document_id = control_plane.create_document(conn, title="測試書")
            revision_id, _ = control_plane.create_revision(
                conn,
                document_id=document_id,
                source_sha256=source_sha,
                source_bytes=len(text.encode("utf-8")),
                source_media_type="text/markdown",
                filename="liezhuan.md",
            )
            job_id = control_plane.queue_job(conn, revision_id=revision_id)
            conn.commit()
        return job_id, revision_id, source_sha

    def _job_status(self, job_id):
        with psycopg.connect(self.database_url) as conn:
            return control_plane.get_job_detail(conn, job_id=job_id)["status"]
