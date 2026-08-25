#!/usr/bin/env python3
"""Enumerate validator Task Ledger leaves that are ready to execute.

The command is deliberately read-only. It consumes the small YAML-like front
matter already used by repository task records and emits a deterministic
snapshot for a human or automation loop. It does not call GitHub, change task
metadata, append findings, or create remediation work.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


TERMINAL_STATUSES = frozenset({"cancelled", "closed", "completed", "done"})
TRACKER_KINDS = frozenset({"parent", "root", "tracker"})


class MetadataError(ValueError):
    """Raised when a task record cannot be evaluated deterministically."""


def _split_front_matter(text: str) -> tuple[str, str] | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :])
    raise MetadataError("front matter is missing its closing --- delimiter")


def _split_list(value: str) -> list[str]:
    value = value.strip()
    if not value or value in {"[]", "null", "~"}:
        return []
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1].strip()
    if not value:
        return []
    parts = re.findall(r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\']*\'|[^,]+', value)
    return [part.strip().strip("\"'") for part in parts if part.strip()]


def _parse_value(value: str) -> Any:
    value = value.strip()
    if value in {"", "null", "~"}:
        return None
    if value.lower() in {"true", "yes", "on"}:
        return True
    if value.lower() in {"false", "no", "off"}:
        return False
    if value.startswith("[") and value.endswith("]"):
        return _split_list(value)
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value[1:-1]
    return value


def _parse_front_matter(front_matter: str) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for line_number, line in enumerate(front_matter.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in line:
            raise MetadataError(f"front matter line {line_number} has no ':'")
        key, value = line.split(":", 1)
        key = key.strip()
        if not key:
            raise MetadataError(f"front matter line {line_number} has an empty key")
        fields[key] = _parse_value(value)
    return fields


def _as_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_as_string(item) for item in value if _as_string(item)]
    return _split_list(_as_string(value))


def _reference_key(value: str) -> str:
    """Normalize issue references while preserving task identifiers."""

    normalized = value.strip().lstrip("#").upper()
    numeric = re.fullmatch(r"(?:ME-)?(\d+)", normalized)
    if numeric:
        return numeric.group(1)
    return normalized


def _is_truthy_blocker(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = _as_string(value).lower()
    return bool(text and text not in {"false", "no", "none", "null", "off", "0"})


@dataclass(frozen=True)
class TaskRecord:
    """The metadata needed by the READY rule."""

    task: str
    issue: str
    status: str
    dependencies: tuple[str, ...]
    path: str
    kind: str
    parent: str
    children: tuple[str, ...]
    architecture_decision_blocker: bool

    @property
    def is_tracker(self) -> bool:
        return self.kind.lower() in TRACKER_KINDS or bool(self.children)

    @property
    def is_terminal(self) -> bool:
        return self.status.lower() in TERMINAL_STATUSES

    @property
    def is_completed(self) -> bool:
        return self.status.lower() == "completed"

    @property
    def aliases(self) -> tuple[str, ...]:
        values = [self.task, self.issue]
        if self.issue:
            values.extend((f"ME-{self.issue}", f"#{self.issue}"))
        return tuple(_reference_key(value) for value in values if value)


def _record_from_path(path: Path, root: Path) -> TaskRecord | None:
    parsed = _split_front_matter(path.read_text(encoding="utf-8"))
    if parsed is None:
        return None
    front_matter, _body = parsed
    fields = _parse_front_matter(front_matter)
    task = _as_string(fields.get("task") or fields.get("id"))
    if not task:
        return None
    status = _as_string(fields.get("status"))
    if not status:
        raise MetadataError(f"{path}: task {task} has no status")
    issue = _as_string(fields.get("issue")).lstrip("#")
    kind = _as_string(fields.get("kind")) or "leaf"
    if fields.get("leaf") is False:
        kind = "tracker"
    return TaskRecord(
        task=task,
        issue=issue,
        status=status,
        dependencies=tuple(_as_list(fields.get("depends_on"))),
        path=path.relative_to(root).as_posix(),
        kind=kind,
        parent=_as_string(fields.get("parent") or fields.get("parent_issue")),
        children=tuple(_as_list(fields.get("children"))),
        architecture_decision_blocker=any(
            _is_truthy_blocker(fields.get(key))
            for key in ("architecture_decision_blocker", "architecture_blocker")
        ),
    )


def discover_records(root: Path) -> list[TaskRecord]:
    """Read task records below *root* in stable path order."""

    if not root.is_dir():
        raise MetadataError(f"task root does not exist or is not a directory: {root}")
    records = []
    for path in sorted(root.rglob("*.md")):
        record = _record_from_path(path, root)
        if record is not None:
            records.append(record)
    return sorted(records, key=lambda record: (record.task, record.path))


def _build_index(records: Iterable[TaskRecord]) -> dict[str, TaskRecord]:
    index: dict[str, TaskRecord] = {}
    for record in records:
        for alias in record.aliases:
            existing = index.get(alias)
            if existing is not None and existing != record:
                raise MetadataError(
                    f"ambiguous task reference {alias}: {existing.path}, {record.path}"
                )
            index[alias] = record
    return index


def _resolve(reference: str, index: dict[str, TaskRecord]) -> TaskRecord | None:
    return index.get(_reference_key(reference))


def evaluate(records: list[TaskRecord]) -> dict[str, Any]:
    """Return a deterministic READY/blocked/reconciliation snapshot."""

    index = _build_index(records)
    ready: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for record in records:
        if record.is_tracker or record.is_terminal:
            continue
        reasons: list[str] = []
        for dependency in record.dependencies:
            resolved = _resolve(dependency, index)
            if resolved is None:
                reasons.append(f"dependency {dependency} has no task metadata")
            elif not resolved.is_terminal or resolved.status.lower() != "completed":
                reasons.append(
                    f"dependency {dependency} is {resolved.status}, not completed"
                )
        if record.architecture_decision_blocker:
            reasons.append("explicit architecture-decision blocker is recorded")
        item = {
            "task": record.task,
            "issue": record.issue,
            "status": record.status,
            "path": record.path,
            "depends_on": list(record.dependencies),
        }
        if reasons:
            item["reasons"] = reasons
            blocked.append(item)
        else:
            ready.append(item)

    def children_for(tracker: TaskRecord) -> list[TaskRecord]:
        if tracker.children:
            return [
                child
                for ref in tracker.children
                if (child := _resolve(ref, index)) is not None
            ]
        return [
            record
            for record in records
            if record.parent and _resolve(record.parent, index) == tracker
        ]

    reconciliation: list[dict[str, Any]] = []
    for tracker in records:
        if not tracker.is_tracker:
            continue
        children = children_for(tracker)
        missing = [ref for ref in tracker.children if _resolve(ref, index) is None]
        reconciliation.append(
            {
                "task": tracker.task,
                "issue": tracker.issue,
                "path": tracker.path,
                "children": [child.task for child in children],
                "missing_children": missing,
                "eligible_for_reconciliation": bool(children)
                and not missing
                and all(child.is_completed for child in children),
            }
        )

    return {
        "rule": {
            "leaf": "record is not a tracker and has an open status",
            "dependencies": "every declared dependency resolves to status completed",
            "blocker": "no explicit architecture_decision_blocker or architecture_blocker is truthy",
            "mutation": "none; enumeration is read-only",
        },
        "record_count": len(records),
        "ready": ready,
        "blocked": blocked,
        "reconciliation": reconciliation,
    }


def _render_text(snapshot: dict[str, Any]) -> str:
    lines = [f"READY validator leaves ({len(snapshot['ready'])}):"]
    for item in snapshot["ready"]:
        lines.append(f"  {item['task']} ({item['issue'] or 'no issue'}) - {item['path']}")
    lines.append(f"BLOCKED validator leaves ({len(snapshot['blocked'])}):")
    for item in snapshot["blocked"]:
        lines.append(f"  {item['task']}: {'; '.join(item['reasons'])}")
    eligible = [
        item for item in snapshot["reconciliation"] if item["eligible_for_reconciliation"]
    ]
    lines.append(f"RECONCILIATION-ELIGIBLE trackers ({len(eligible)}):")
    for item in eligible:
        lines.append(f"  {item['task']} ({item['issue'] or 'no issue'})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = Path(__file__).resolve().parents[1] / "docs" / "tasks" / "validator"
    parser.add_argument("--root", type=Path, default=default_root, help="task-record directory")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    try:
        snapshot = evaluate(discover_records(args.root.resolve()))
    except (OSError, MetadataError) as error:
        print(f"validator-ready: error: {error}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(snapshot, indent=2, sort_keys=True))
    else:
        print(_render_text(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
