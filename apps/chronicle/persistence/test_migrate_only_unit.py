"""C2-R1-T16 migration-only mode unit tests (offline, no database).

Covers the ``--migrate-only`` mode of
``apps/chronicle/persistence/chronicle_persist.py``:

* the mode does not require ``--bundle``/``--catalog``;
* artifact-import flags are mutually exclusive with ``--migrate-only`` and
  fail with an explicit parameter error;
* the mode reuses the existing migration runner, imports no artifacts, and
  reports only schema results;
* re-running against an already-migrated database is a no-op returning the
  recorded versions (migration idempotence contract).
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import chronicle_persist  # noqa: E402
from common import PersistenceError  # noqa: E402


class _FakeCursor:
    def __init__(self, conn: "_FakeConnection", query: str, params=None):
        self._conn = conn
        self._query = query
        self._params = params

    def fetchone(self):
        return self._conn._fetchone(self._query, self._params)

    def fetchall(self):
        return self._conn._fetchall(self._query, self._params)


class _FakeConnection:
    """Minimal psycopg stand-in driving the real ``apply_migrations``."""

    def __init__(self) -> None:
        self.recorded: dict[str, str] = {}
        self.statements: list[str] = []

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *args) -> bool:
        return False

    def transaction(self) -> "_FakeConnection":
        return self

    def execute(self, query, params=None) -> _FakeCursor:
        text = query if isinstance(query, str) else str(query)
        self.statements.append(text)
        if text.lstrip().upper().startswith("INSERT INTO CHRONICLE.SCHEMA_MIGRATIONS"):
            version, checksum = params
            self.recorded[str(version)] = str(checksum)
        return _FakeCursor(self, text, params)

    def _fetchone(self, query: str, params):
        normalized = " ".join(query.split()).upper()
        if normalized.startswith("SELECT CHECKSUM FROM CHRONICLE.SCHEMA_MIGRATIONS"):
            version = params[0]
            if version in self.recorded:
                return (self.recorded[version],)
            return None
        raise AssertionError(f"unexpected fetchone query: {query!r}")

    def _fetchall(self, query: str, params):
        normalized = " ".join(query.split()).upper()
        if normalized.startswith("SELECT VERSION, CHECKSUM FROM CHRONICLE.SCHEMA_MIGRATIONS"):
            return sorted(self.recorded.items())
        raise AssertionError(f"unexpected fetchall query: {query!r}")


def _run_main(argv: list[str]) -> tuple[int, str]:
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        code = chronicle_persist.main(argv)
    return code, stderr.getvalue()


class MigrateOnlyParserTests(unittest.TestCase):
    def test_migrate_only_needs_no_catalog(self) -> None:
        args = chronicle_persist.build_parser().parse_args(
            ["--database-url", "postgresql://example/db", "--migrate-only"]
        )
        self.assertTrue(args.migrate_only)
        self.assertIsNone(args.catalog)
        self.assertEqual(args.bundle, [])
        self.assertEqual(args.resolution, [])

    def test_migrate_only_rejects_bundle(self) -> None:
        code, stderr = _run_main(
            [
                "--database-url",
                "postgresql://example/db",
                "--migrate-only",
                "--bundle",
                "wudi=/tmp/wudi.json",
            ]
        )
        self.assertEqual(code, 2)
        self.assertIn("--migrate-only cannot be combined with --bundle", stderr)

    def test_migrate_only_rejects_resolution(self) -> None:
        code, stderr = _run_main(
            [
                "--database-url",
                "postgresql://example/db",
                "--migrate-only",
                "--resolution",
                "/tmp/links.json",
            ]
        )
        self.assertEqual(code, 2)
        self.assertIn("--migrate-only cannot be combined with --resolution", stderr)

    def test_migrate_only_rejects_catalog(self) -> None:
        code, stderr = _run_main(
            [
                "--database-url",
                "postgresql://example/db",
                "--migrate-only",
                "--catalog",
                "/tmp/catalog.json",
            ]
        )
        self.assertEqual(code, 2)
        self.assertIn("--migrate-only cannot be combined with --catalog", stderr)

    def test_migrate_only_requires_database_url(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=False):
            env = {k: v for k, v in __import__("os").environ.items() if k != "CHRONICLE_DATABASE_URL"}
            with mock.patch("os.environ", env):
                code, stderr = _run_main(["--migrate-only"])
        self.assertEqual(code, 2)
        self.assertIn("database URL is required", stderr)

    def test_import_mode_still_requires_catalog(self) -> None:
        code, stderr = _run_main(
            [
                "--database-url",
                "postgresql://example/db",
                "--bundle",
                "wudi=/tmp/wudi.json",
            ]
        )
        self.assertEqual(code, 2)
        self.assertIn("--catalog is required unless --migrate-only is used", stderr)


class MigrateOnlyRunnerTests(unittest.TestCase):
    def test_reports_schema_versions_only(self) -> None:
        conn = _FakeConnection()
        with mock.patch.object(
            chronicle_persist.psycopg, "connect", return_value=conn
        ):
            versions = chronicle_persist.migrate_only_to_url("postgresql://example/db")
        self.assertGreater(len(versions), 0)
        for entry in versions:
            self.assertEqual(set(entry), {"version", "checksum"})
        self.assertEqual(
            [entry["version"] for entry in versions],
            sorted(entry["version"] for entry in versions),
        )
        # No artifact rows reach the database: the only writes are migration
        # bookkeeping (DDL plus INSERTs into schema_migrations). Any other
        # data-modifying statement would mean an artifact import slipped in.
        for statement in conn.statements:
            first_word = statement.split(None, 1)[0].upper().rstrip(";")
            if first_word in {"INSERT", "UPDATE", "DELETE", "MERGE", "COPY"}:
                normalized = " ".join(statement.split()).upper()
                self.assertIn(
                    "SCHEMA_MIGRATIONS",
                    normalized,
                    f"migrate-only must not import artifacts: {statement[:120]!r}",
                )

    def test_rerun_is_idempotent(self) -> None:
        conn = _FakeConnection()
        with mock.patch.object(
            chronicle_persist.psycopg, "connect", return_value=conn
        ):
            first = chronicle_persist.migrate_only_to_url("postgresql://example/db")
            second = chronicle_persist.migrate_only_to_url("postgresql://example/db")
        self.assertEqual(first, second)

    def test_main_writes_migration_report(self) -> None:
        conn = _FakeConnection()
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "sub" / "migration-report.json"
            with mock.patch.object(
                chronicle_persist.psycopg, "connect", return_value=conn
            ):
                code, stderr = _run_main(
                    [
                        "--database-url",
                        "postgresql://example/db",
                        "--migrate-only",
                        "--report",
                        str(report_path),
                    ]
                )
                self.assertEqual(code, 0)
                self.assertIn("chronicle migrate: PASS", stderr)
                report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["schema"], "chronicle.migration-run")
        self.assertEqual(report["version"], "0.1")
        self.assertTrue(report["passed"])
        self.assertGreater(len(report["migrations"]), 0)

    def test_empty_database_url_fails(self) -> None:
        with self.assertRaises(PersistenceError):
            chronicle_persist.migrate_only_to_url("")


if __name__ == "__main__":
    unittest.main()
