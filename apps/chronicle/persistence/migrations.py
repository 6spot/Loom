"""Chronicle-owned PostgreSQL migration runner."""

from __future__ import annotations

from pathlib import Path

from common import PersistenceConflict, PersistenceError, sha256_bytes


MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def migration_files() -> list[Path]:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        raise PersistenceError(f"no Chronicle migrations found under {MIGRATIONS_DIR}")
    return files


def apply_migrations(conn) -> None:
    with conn.transaction():
        conn.execute("CREATE SCHEMA IF NOT EXISTS chronicle")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chronicle.schema_migrations (
                version text PRIMARY KEY,
                checksum text NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )

        for path in migration_files():
            raw = path.read_bytes()
            checksum = sha256_bytes(raw)
            version = path.name
            row = conn.execute(
                "SELECT checksum FROM chronicle.schema_migrations WHERE version = %s",
                (version,),
            ).fetchone()
            if row is not None:
                if row[0] != checksum:
                    raise PersistenceConflict(
                        f"migration {version} checksum changed: database={row[0]} file={checksum}"
                    )
                continue

            conn.execute(raw.decode("utf-8"))
            conn.execute(
                "INSERT INTO chronicle.schema_migrations(version, checksum) VALUES (%s, %s)",
                (version, checksum),
            )
