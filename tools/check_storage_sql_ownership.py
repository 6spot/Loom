#!/usr/bin/env python3
"""Enforce Loom engine and registered Application PostgreSQL ownership boundaries.

`loom-storage` remains the exclusive owner of Loom engine PostgreSQL/SQLx
implementation concerns. Architecture Amendment 0006 additionally permits a
closed set of explicitly registered Application-owned product persistence
roots whose records are outside Loom Runtime/World/Timeline authority.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORAGE = ROOT / "crates" / "loom-storage"
BENCH = ROOT / "crates" / "loom-bench"
VALIDATOR = ROOT / "apps" / "loom-validator"
ENGINE_SQL_ROOTS = (STORAGE / "migrations", STORAGE / "sql")

# Closed architecture registry. Adding another Application product SQL root is
# an architecture change, not a generic apps/** exemption.
APPLICATION_PRODUCT_PERSISTENCE = {
    ROOT / "apps" / "chronicle" / "persistence": {
        "sql_roots": (ROOT / "apps" / "chronicle" / "persistence" / "migrations",),
        "boundary_doc": ROOT / "apps" / "chronicle" / "docs" / "persistence.md",
        "connection_contract": "CHRONICLE_DATABASE_URL",
    },
}
APPLICATION_SQL_ROOTS = tuple(
    sql_root
    for registration in APPLICATION_PRODUCT_PERSISTENCE.values()
    for sql_root in registration["sql_roots"]
)
ALLOWED_SQL_ROOTS = ENGINE_SQL_ROOTS + APPLICATION_SQL_ROOTS

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

VALIDATOR_FORBIDDEN_RUST_PATTERNS = {
    "loom-storage import": re.compile(r"\bloom_storage\b"),
    "loom-runtime import": re.compile(r"\bloom_runtime\b"),
    "loom-boundary import": re.compile(r"\bloom_boundary\b"),
    "loom-core import": re.compile(r"\bloom_core\b"),
    "loom-protocol import": re.compile(r"\bloom_protocol\b"),
    "loom-capability import": re.compile(r"\bloom_capability\b"),
    "loom-agency import": re.compile(r"\bloom_agency\b"),
    "loom-neutral import": re.compile(r"\bloom_neutral\b"),
    "sqlx path": re.compile(r"\bsqlx::"),
    "tokio-postgres path": re.compile(r"\btokio_postgres::"),
    "postgres client path": re.compile(r"\bpostgres::(?:Client|Config|Transaction)\b"),
    "PgStorage authority": re.compile(r"\bPgStorage\b"),
}

VALIDATOR_FORBIDDEN_CARGO_PATTERNS = {
    "implementation workspace dependency": re.compile(
        r"(?m)^\s*loom-(?:server|storage|runtime|boundary|core|protocol|capability|agency|neutral)\s*="
    ),
    "sqlx dependency": re.compile(r"(?m)^\s*sqlx\s*="),
    "tokio-postgres dependency": re.compile(r"(?m)^\s*tokio-postgres\s*="),
    "postgres dependency": re.compile(r"(?m)^\s*postgres\s*="),
    "pgvector dependency": re.compile(r"(?m)^\s*pgvector\s*="),
    "diesel dependency": re.compile(r"(?m)^\s*diesel\s*="),
    "object-store dependency": re.compile(r"(?m)^\s*object_store\s*="),
    "axum dependency": re.compile(r"(?m)^\s*axum\s*="),
    "reqwest dependency": re.compile(r"(?m)^\s*reqwest\s*="),
}


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


def check_application_product_registrations(errors: list[str]) -> None:
    for persistence_root, registration in APPLICATION_PRODUCT_PERSISTENCE.items():
        if not persistence_root.is_dir():
            errors.append(
                f"registered Application persistence root missing: {persistence_root.relative_to(ROOT)}"
            )
            continue

        boundary_doc = registration["boundary_doc"]
        if not boundary_doc.is_file():
            errors.append(
                f"registered Application persistence boundary doc missing: {boundary_doc.relative_to(ROOT)}"
            )
        else:
            text = boundary_doc.read_text(encoding="utf-8")
            connection_contract = registration["connection_contract"]
            if connection_contract not in text:
                errors.append(
                    "registered Application persistence boundary doc does not declare "
                    f"{connection_contract}: {boundary_doc.relative_to(ROOT)}"
                )

        for sql_root in registration["sql_roots"]:
            if not sql_root.is_dir():
                errors.append(
                    f"registered Application SQL root missing: {sql_root.relative_to(ROOT)}"
                )
            elif not is_under(sql_root, persistence_root):
                errors.append(
                    "registered Application SQL root escapes persistence boundary: "
                    f"{sql_root.relative_to(ROOT)}"
                )

        # A product store must never claim the Loom engine production connection.
        for path in persistence_root.rglob("*.py"):
            if path.name.startswith("test_"):
                continue
            text = path.read_text(encoding="utf-8")
            if "LOOM_DATABASE_URL" in text:
                errors.append(
                    "Loom engine database authority leaked into registered Application persistence: "
                    f"{path.relative_to(ROOT)}"
                )


def check_sql_file_locations(errors: list[str]) -> None:
    for path in ROOT.rglob("*.sql"):
        if any(is_under(path, allowed) for allowed in ALLOWED_SQL_ROOTS):
            continue
        errors.append(
            f"SQL file outside Loom Storage or registered Application product ownership: "
            f"{path.relative_to(ROOT)}"
        )


def check_non_storage_rust(errors: list[str]) -> None:
    for root in checked_roots():
        if not root.exists():
            continue
        for path in root.rglob("*.rs"):
            if is_under(path, STORAGE):
                continue
            if is_under(path, BENCH):
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
            if is_under(path, BENCH):
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


def check_validator_boundary(errors: list[str]) -> None:
    """Keep validator production code on supported public consumer surfaces only.

    Real InMemory/PostgreSQL service composition for scenario evidence is
    test-only (`apps/loom-validator/tests/`), the same pattern `loom-client` uses
    to exercise its boundary, so the `tests/` tree is excluded. Production
    `src/` and the `[dependencies]` section must remain on `loom-api` /
    `loom-client`; only test-only dev-dependencies compose real services.
    """
    if not VALIDATOR.exists():
        return

    tests_dir = VALIDATOR / "tests"
    for path in VALIDATOR.rglob("*.rs"):
        if tests_dir in path.parents:
            continue
        text = path.read_text(encoding="utf-8")
        for label, pattern in VALIDATOR_FORBIDDEN_RUST_PATTERNS.items():
            if pattern.search(text):
                errors.append(
                    f"{label} leaked into validator: {path.relative_to(ROOT)}"
                )

    for path in VALIDATOR.rglob("Cargo.toml"):
        text = path.read_text(encoding="utf-8")
        # Only the production [dependencies] section is constrained; test-only
        # dev-dependencies compose real services for scenario evidence.
        production_deps = text.split("[dev-dependencies]", 1)[0]
        for label, pattern in VALIDATOR_FORBIDDEN_CARGO_PATTERNS.items():
            if pattern.search(production_deps):
                errors.append(f"{label} in validator: {path.relative_to(ROOT)}")


def main() -> int:
    errors: list[str] = []
    check_application_product_registrations(errors)
    check_sql_file_locations(errors)
    check_non_storage_rust(errors)
    check_non_storage_cargo(errors)
    check_storage_inline_sql(errors)
    check_validator_boundary(errors)

    if errors:
        print("storage SQL ownership check failed:", file=sys.stderr)
        for error in sorted(set(errors)):
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("storage SQL ownership check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
