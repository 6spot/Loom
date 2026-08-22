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

FORBIDDEN_RUST_PATTERNS = {
    "sqlx path": re.compile(r"\bsqlx::"),
    "PgPool": re.compile(r"\bPgPool\b"),
    "PgConnection": re.compile(r"\bPgConnection\b"),
    "PgTransaction": re.compile(r"\bPgTransaction\b"),
    "SQLx Postgres type": re.compile(r"\bsqlx\s*::[^\n;]*\bPostgres\b"),
    "tokio-postgres path": re.compile(r"\btokio_postgres::"),
    "postgres client path": re.compile(r"\bpostgres::(?:Client|Config|Transaction)\b"),
}

FORBIDDEN_CARGO_PATTERNS = {
    "sqlx dependency": re.compile(r"(?m)^\s*sqlx\s*="),
    "tokio-postgres dependency": re.compile(r"(?m)^\s*tokio-postgres\s*="),
    "postgres dependency": re.compile(r"(?m)^\s*postgres\s*="),
    "pgvector dependency": re.compile(r"(?m)^\s*pgvector\s*="),
    "diesel dependency": re.compile(r"(?m)^\s*diesel\s*="),
}

INLINE_SQL_PATTERN = re.compile(
    r"sqlx::(?:query|query_scalar)(?:\s*::<[^)]*>)?\s*\(\s*\"",
    re.MULTILINE,
)


def is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def checked_roots() -> list[Path]:
    roots = [ROOT / "crates", ROOT / "tests"]
    apps = ROOT / "apps"
    if apps.exists():
        roots.append(apps)
    capabilities = ROOT / "capabilities"
    if capabilities.exists():
        roots.append(capabilities)
    adapters = ROOT / "adapters"
    if adapters.exists():
        roots.append(adapters)
    return roots


def check_sql_file_locations(errors: list[str]) -> None:
    for path in ROOT.rglob("*.sql"):
        if any(is_under(path, allowed) for allowed in ALLOWED_SQL_ROOTS):
            continue
        errors.append(
            f"SQL file outside loom-storage ownership: {path.relative_to(ROOT)}"
        )


def check_non_storage_rust(errors: list[str]) -> None:
    for root in checked_roots():
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
    for root in checked_roots():
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


def production_rust(path: Path, text: str) -> str:
    """Return only Rust that is compiled as production storage implementation.

    A file named `tests.rs` under `loom-storage/src` is a module referenced only
    through `#[cfg(test)] mod tests;`. Inline SQL there is schema/constraint test
    instrumentation, not a production persistence path. A file-local test module
    at the end of a production source file is treated the same way.

    There is intentionally no production-path allowlist.
    """
    if path.name == "tests.rs":
        return ""
    return text.split("#[cfg(test)]", 1)[0]


def check_storage_inline_sql(errors: list[str]) -> None:
    source_root = STORAGE / "src"
    for path in source_root.rglob("*.rs"):
        text = production_rust(path, path.read_text(encoding="utf-8"))
        if not INLINE_SQL_PATTERN.search(text):
            continue
        relative = path.relative_to(ROOT)
        errors.append(
            f"inline production SQL in {relative}; move the statement to "
            "crates/loom-storage/sql/<domain>/ and load it with include_str!"
        )


def main() -> int:
    errors: list[str] = []
    check_sql_file_locations(errors)
    check_non_storage_rust(errors)
    check_non_storage_cargo(errors)
    check_storage_inline_sql(errors)

    if errors:
        print("storage SQL ownership check failed:", file=sys.stderr)
        for error in sorted(set(errors)):
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("storage SQL ownership check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
