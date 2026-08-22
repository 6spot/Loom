#!/usr/bin/env python3
"""Enforce Loom's PostgreSQL/SQL ownership boundary.

`loom-storage` is the only crate allowed to own SQLx/PostgreSQL implementation
concerns. Runtime and higher layers consume persistence ports instead of SQL,
connection pools, transactions, or table-level authority.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORAGE = ROOT / "crates" / "loom-storage"
ALLOWED_SQL_ROOTS = (STORAGE / "migrations", STORAGE / "sql")

# Implementation-level PostgreSQL/SQLx symbols that must not cross the storage
# adapter boundary. Keep this list intentionally concrete to avoid banning
# architecture prose that merely discusses persistence.
FORBIDDEN_RUST_PATTERNS = {
    "sqlx path": re.compile(r"\bsqlx::"),
    "PgPool": re.compile(r"\bPgPool\b"),
    "PgConnection": re.compile(r"\bPgConnection\b"),
    "PgTransaction": re.compile(r"\bPgTransaction\b"),
    "SQLx Postgres type": re.compile(r"\bsqlx\s*::[^\n;]*\bPostgres\b"),
}

FORBIDDEN_CARGO_PATTERNS = {
    "sqlx dependency": re.compile(r"(?m)^\s*sqlx\s*="),
}


def is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def production_roots() -> list[Path]:
    roots = [ROOT / "crates"]
    apps = ROOT / "apps"
    if apps.exists():
        roots.append(apps)
    return roots


def check_sql_file_locations(errors: list[str]) -> None:
    for path in ROOT.rglob("*.sql"):
        if any(is_under(path, allowed) for allowed in ALLOWED_SQL_ROOTS):
            continue
        errors.append(
            f"SQL file outside loom-storage ownership: {path.relative_to(ROOT)}"
        )


def check_non_storage_rust(errors: list[str]) -> None:
    for root in production_roots():
        if not root.exists():
            continue
        for path in root.rglob("*.rs"):
            if is_under(path, STORAGE):
                continue
            text = path.read_text(encoding="utf-8")
            for label, pattern in FORBIDDEN_RUST_PATTERNS.items():
                if pattern.search(text):
                    errors.append(
                        f"{label} leaked outside loom-storage: {path.relative_to(ROOT)}"
                    )


def check_non_storage_cargo(errors: list[str]) -> None:
    for root in production_roots():
        if not root.exists():
            continue
        for path in root.rglob("Cargo.toml"):
            if is_under(path, STORAGE):
                continue
            text = path.read_text(encoding="utf-8")
            for label, pattern in FORBIDDEN_CARGO_PATTERNS.items():
                if pattern.search(text):
                    errors.append(
                        f"{label} outside loom-storage: {path.relative_to(ROOT)}"
                    )


def main() -> int:
    errors: list[str] = []
    check_sql_file_locations(errors)
    check_non_storage_rust(errors)
    check_non_storage_cargo(errors)

    if errors:
        print("storage SQL ownership check failed:", file=sys.stderr)
        for error in sorted(set(errors)):
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("storage SQL ownership check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
