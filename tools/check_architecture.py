#!/usr/bin/env python3
"""Validate Loom's Rust architecture dependency and infrastructure policy.

This checker intentionally uses `cargo metadata` rather than parsing Cargo.toml
files itself for dependency edges. It enforces the physical dependency DAG
documented in `docs/architecture/governance.md` and rejects layer-specific
implementation leaks before they can become established conventions.

The checker is not a substitute for architecture review. It is a mechanical
floor: a new dependency edge or persistence-ownership exception that is not
explicitly allowed must first be reviewed and added to the architecture contract
rather than bypassed here.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# `A: {B, C}` means package A may directly depend on workspace packages B/C.
# Absence from this map is deliberate: new framework crates must be classified
# by architecture review before they are accepted into the workspace.
FRAMEWORK_ALLOWLIST: dict[str, set[str]] = {
    "loom-core": set(),
    "loom-protocol": {"loom-core"},
    "loom-api": {"loom-core", "loom-protocol"},
    "loom-capability": {"loom-core", "loom-protocol"},
    "loom-agency": {"loom-core", "loom-protocol"},
    "loom-runtime": {
        "loom-core",
        "loom-protocol",
        "loom-api",
        "loom-capability",
        "loom-agency",
    },
    "loom-storage": {"loom-core", "loom-runtime"},
    "loom-boundary": {"loom-api"},
    "loom-client": {"loom-api"},
    "loom-validator": {"loom-api", "loom-client"},
    "loom-composition-tests": {
        "loom-api",
        "loom-capability",
        "loom-core",
        "loom-neutral",
        "loom-protocol",
        "loom-runtime",
        "loom-storage",
    },
    "loom-bench": {
        "loom-api",
        "loom-agency",
        "loom-capability",
        "loom-core",
        "loom-protocol",
        "loom-runtime",
        "loom-storage",
    },
}

# External crates that would materially violate a layer boundary if they leak
# into a contract/kernel crate. This list is intentionally conservative and can
# grow as the implementation adopts additional infrastructure libraries.
FORBIDDEN_EXTERNAL: dict[str, set[str]] = {
    "loom-core": {
        "axum",
        "hyper",
        "object_store",
        "pgvector",
        "reqwest",
        "sqlx",
        "tokio-postgres",
        "tonic",
        "tower",
        "tower-http",
    },
    "loom-protocol": {
        "axum",
        "hyper",
        "object_store",
        "pgvector",
        "reqwest",
        "sqlx",
        "tokio-postgres",
        "tonic",
        "tower",
        "tower-http",
    },
    "loom-api": {
        "axum",
        "hyper",
        "object_store",
        "pgvector",
        "reqwest",
        "sqlx",
        "tokio-postgres",
        "tonic",
        "tower-http",
    },
    "loom-capability": {
        "axum",
        "hyper",
        "object_store",
        "pgvector",
        "reqwest",
        "sqlx",
        "tokio-postgres",
        "tonic",
        "tower-http",
    },
    "loom-agency": {
        "axum",
        "hyper",
        "object_store",
        "pgvector",
        "reqwest",
        "sqlx",
        "tokio-postgres",
        "tonic",
        "tower-http",
    },
    "loom-runtime": {
        "axum",
        "hyper",
        "object_store",
        "pgvector",
        "reqwest",
        "sqlx",
        "tokio-postgres",
        "tonic",
        "tower-http",
    },
    "loom-storage": {"axum", "hyper", "tonic", "tower-http"},
    "loom-boundary": {
        "object_store",
        "pgvector",
        "sqlx",
        "tokio-postgres",
    },
}


def run_metadata() -> dict:
    result = subprocess.run(
        ["cargo", "metadata", "--format-version", "1"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
        raise SystemExit(result.returncode)
    return json.loads(result.stdout)


def relative_manifest(package: dict) -> Path:
    path = Path(package["manifest_path"]).resolve()
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return path


def allowed_workspace_dependencies(package: dict) -> set[str] | None:
    name = package["name"]
    if name in FRAMEWORK_ALLOWLIST:
        return FRAMEWORK_ALLOWLIST[name]

    manifest = relative_manifest(package)
    parts = manifest.parts

    if parts and parts[0] == "capabilities":
        return {"loom-core", "loom-protocol", "loom-capability"}

    if parts and parts[0] == "adapters" and name.startswith("cognitive-"):
        return {"loom-core", "loom-protocol", "loom-agency"}

    if parts and parts[0] == "apps":
        if name == "loom-server":
            # Server is the composition root. Concrete extension/provider package
            # names are intentionally not enumerated here; they are accepted by
            # path classification below in the direct-edge check.
            return {
                "loom-api",
                "loom-runtime",
                "loom-storage",
                "loom-boundary",
            }
        if name in {"loom-cli", "loom-studio"}:
            return {"loom-api"}

    return None


def is_composition_extension_dependency(package: dict, dependency_name: str, by_name: dict[str, dict]) -> bool:
    if package["name"] != "loom-server":
        return False
    dependency = by_name.get(dependency_name)
    if dependency is None:
        return False
    manifest = relative_manifest(dependency)
    parts = manifest.parts
    return bool(parts and parts[0] in {"capabilities", "adapters"})


def is_production_dependency(dependency: dict) -> bool:
    """Return whether Cargo includes the edge in a normal production build."""
    return dependency.get("kind") in {None, "normal", "build"}


def run_storage_sql_ownership_check() -> int:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "check_storage_sql_ownership.py")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def main() -> int:
    metadata = run_metadata()
    workspace_ids = set(metadata["workspace_members"])
    workspace_packages = [
        package for package in metadata["packages"] if package["id"] in workspace_ids
    ]
    workspace_names = {package["name"] for package in workspace_packages}
    by_name = {package["name"]: package for package in workspace_packages}

    errors: list[str] = []

    for package in sorted(workspace_packages, key=lambda item: item["name"]):
        name = package["name"]
        allowed = allowed_workspace_dependencies(package)
        if allowed is None:
            errors.append(
                f"{name}: workspace package is not classified by architecture policy "
                f"({relative_manifest(package)}). Update governance before adding it."
            )
            continue

        internal_dependencies = {
            dependency["name"]
            for dependency in package["dependencies"]
            if dependency["name"] in workspace_names
            and is_production_dependency(dependency)
        }

        for dependency_name in sorted(internal_dependencies - allowed):
            if is_composition_extension_dependency(package, dependency_name, by_name):
                continue
            errors.append(
                f"{name} -> {dependency_name}: forbidden workspace dependency edge"
            )

        forbidden_external = FORBIDDEN_EXTERNAL.get(name, set())
        external_dependencies = {
            dependency["name"]
            for dependency in package["dependencies"]
            if dependency["name"] not in workspace_names
            and is_production_dependency(dependency)
        }
        for dependency_name in sorted(external_dependencies & forbidden_external):
            errors.append(
                f"{name} -> {dependency_name}: infrastructure dependency leaks into "
                "a layer where it is forbidden"
            )

    if errors:
        print("Loom architecture policy violations:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print(
            "\nSee docs/architecture/governance.md. Change the architecture contract "
            "before changing this checker.",
            file=sys.stderr,
        )
        return 1

    if run_storage_sql_ownership_check() != 0:
        print(
            "\nSee docs/architecture/governance.md and "
            "crates/loom-storage/sql/README.md. PostgreSQL implementation details "
            "must remain owned by loom-storage.",
            file=sys.stderr,
        )
        return 1

    print("Loom architecture dependency policy: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
