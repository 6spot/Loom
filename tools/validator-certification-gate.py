#!/usr/bin/env python3
"""Run the current-main Validator certification gate.

The gate is deliberately an evidence collector, not a second Validator.  It
runs the existing public-consumer test targets and the controlled PostgreSQL
18 gate, then joins their real test summaries to the T22 manifest.  Manifest
gaps remain explicit non-pass rows; this script never upgrades them based on
an aggregate command result.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/tasks/validator-recert/stage-3/t22-certification-manifest.md"
REPORT = Path(
    os.environ.get(
        "LOOM_T24_REPORT_PATH", ROOT / "target/validator/t24-validator-certification-gate.json"
    )
)
LOG_DIR = REPORT.parent / "t24-logs"
EXPECTED_CANDIDATE = "34fc8efa77cf61d8a9261eaec575bbe111615618"
T24_PG_DATABASE = "loom_t24_certification"
AUTHORIZED_T24_PATHS = frozenset(
    {
        "docs/tasks/validator-recert/stage-3/t24-validator-certification-gate.md",
        "tools/validator-certification-gate.py",
        "tools/validator-certification-gate.sh",
    }
)

COMPLETED_CV_IDS = [
    "CV-001",
    "CV-002",
    "CV-003",
    "CV-004",
    "CV-005",
    "CV-006",
    "CV-007",
    "CV-008",
    "CV-009",
    "CV-010",
    "CV-011",
    "CV-012",
    "CV-013",
    "CV-014",
    "CV-015",
    "CV-016",
    "CV-020",
    "CV-021",
    "CV-022",
    "CV-023",
    "CV-024",
    "CV-025",
    "CV-026",
    "CV-027",
    "CV-030",
    "CV-031",
    "CV-032",
    "CV-033",
    "CV-038",
    "CV-039",
    "CV-040",
]

TEST_TARGETS = {
    "lifecycle": ["bash", "tools/test.sh", "-p", "loom-validator", "--test", "lifecycle", "--", "--test-threads=1"],
    "replay_fork": ["bash", "tools/test.sh", "-p", "loom-validator", "--test", "replay_fork", "--", "--test-threads=1"],
    "runtime_authority": ["bash", "tools/test.sh", "-p", "loom-validator", "--test", "runtime_authority", "--", "--test-threads=1"],
    "world_binding": ["bash", "tools/test.sh", "-p", "loom-validator", "--test", "world_binding", "--", "--test-threads=1"],
    "action_ingress": ["bash", "tools/test.sh", "-p", "loom-validator", "--test", "action_ingress", "--", "--test-threads=1"],
    "scheduler": ["bash", "tools/test.sh", "-p", "loom-validator", "--test", "scheduler", "--", "--test-threads=1"],
    "agency": ["bash", "tools/test.sh", "-p", "loom-validator", "--test", "agency", "--", "--test-threads=1"],
    "world_time": ["bash", "tools/test.sh", "-p", "loom-validator", "--test", "world_time", "--", "--test-threads=1"],
    "query_catalog": ["bash", "tools/test.sh", "-p", "loom-validator", "--test", "query_catalog", "--", "--test-threads=1"],
    "semantic_blob": ["bash", "tools/test.sh", "-p", "loom-validator", "--test", "semantic_blob", "--", "--test-threads=1"],
    "provenance": ["bash", "tools/test.sh", "-p", "loom-validator", "--test", "provenance", "--", "--test-threads=1"],
    "change_feed": ["bash", "tools/test.sh", "-p", "loom-validator", "--test", "change_feed", "--", "--test-threads=1"],
    "backend_evidence": ["cargo", "test", "-p", "loom-validator", "--test", "backend_evidence", "--all-features", "--", "--nocapture"],
    "required_live": ["cargo", "test", "-p", "loom-validator", "--test", "required_live", "--all-features", "--", "--nocapture"],
    "restart_evidence": ["cargo", "test", "-p", "loom-validator", "--test", "restart_evidence", "--all-features", "--", "--nocapture"],
    "validator_lib": ["cargo", "test", "-p", "loom-validator", "--lib", "--all-features", "--", "--nocapture"],
    "validator_pg18": ["bash", "tools/validator-pg18-gate.sh"],
}


def command_text(command: list[str]) -> str:
    return " ".join(command)


def split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def cv_ids(cell: str) -> list[str]:
    # Only the leading selector is the row's owned CV set. Later mentions are
    # often reused test names (for example CV-007 cites the CV-006 fixture).
    ids: set[str] = set()
    for part in cell.split(";"):
        selector = part.strip().replace("`", "")
        # A row may own multiple CVs (CV-002; CV-015), while later prose can
        # cite another row's fixture ("same exact tests as CV-006").
        if not selector.startswith("CV-"):
            continue
        for start, end in re.findall(r"CV-(\d{3})(?:\.\.CV-(\d{3}))?", selector):
            first = int(start)
            last = int(end or start)
            ids.update(f"CV-{number:03d}" for number in range(first, last + 1))
    return sorted(ids, key=lambda value: int(value[3:]))


def suite_for(row: dict[str, object]) -> str:
    required_command = str(row.get("required_command", ""))
    command_match = re.search(r"(?:^|\s)--test(?:=|\s+)([A-Za-z0-9_-]+)", required_command)
    if command_match:
        return command_match.group(1)
    validator = str(row["validator"])
    match = re.search(r"apps/loom-validator/tests/([^:]+)\.rs", validator)
    if match:
        return match.group(1)
    if "Validator unit evidence" in validator:
        return "validator_lib"
    return "validator_lib"


def parse_manifest() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = split_row(line)
        if len(cells) != 9 or cells[0] in {"Capability", "---"}:
            continue
        # The formal client/CLI row mentions the whole CV range as context but
        # is intentionally not a Validator scenario row. Do not duplicate
        # those IDs into the per-CV evidence matrix.
        ids = [] if cells[2].startswith("No separate public Validator CV") else cv_ids(cells[2])
        status_match = re.search(r"`(ready|gap|intentionally non-Validator-covered)`", cells[7])
        if not status_match:
            continue
        status = status_match.group(1)
        required_pg = "**Required:**" in cells[4]
        restart_required = "**Required:**" in cells[5] and "restart" in cells[5].lower()
        rows.append(
            {
                "capability": cells[0],
                "validator": cells[2],
                "pg_requirement": cells[4],
                "pg18_required": required_pg,
                "restart_required": restart_required,
                "required_command": cells[6],
                "status": status,
                "reason": cells[7],
                "cv_ids": ids,
            }
        )
    if not rows:
        raise RuntimeError(f"no T22 rows found in {MANIFEST}")
    return rows


def run_command(name: str, command: list[str]) -> dict[str, object]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    command_env = os.environ.copy()
    preparation = ""
    if name == "validator_pg18":
        service = subprocess.run(
            ["bash", "tools/postgres-test.sh", "up"],
            cwd=ROOT,
            env=command_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        preparation += service.stdout
        if service.returncode == 0:
            reset = subprocess.run(
                [
                    "docker",
                    "compose",
                    "--project-name",
                    "loom",
                    "-f",
                    "compose.test-db.yaml",
                    "exec",
                    "-T",
                    "postgres-test",
                    "psql",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-U",
                    "loom",
                    "-d",
                    "postgres",
                    "-c",
                    f"DROP DATABASE IF EXISTS {T24_PG_DATABASE}",
                    "-c",
                    f"CREATE DATABASE {T24_PG_DATABASE}",
                ],
                cwd=ROOT,
                env=command_env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            preparation += reset.stdout
            if reset.returncode != 0:
                command_env["LOOM_T24_PG_PREPARATION_FAILED"] = "true"
        else:
            command_env["LOOM_T24_PG_PREPARATION_FAILED"] = "true"
        command_env["LOOM_TEST_POSTGRES_URL"] = (
            f"postgresql://loom:loom@127.0.0.1:15432/{T24_PG_DATABASE}"
        )
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=command_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output = preparation + completed.stdout
    log_path = LOG_DIR / f"{name}.log"
    log_path.write_text(output, encoding="utf-8")
    summaries = re.findall(r"test result: (ok|FAILED)\.\s+(.+)", output)
    passed = sum(1 for state, _ in summaries if state == "ok")
    failed = sum(1 for state, _ in summaries if state == "FAILED")
    executed = bool(summaries) and all(
        state == "ok" and not re.search(r"(?:^|;\s)0 passed", detail)
        for state, detail in summaries
    )
    if name == "validator_pg18":
        executed = executed and "T20 PostgreSQL live matrix:" in output
    return {
        "command_id": name,
        "command": command_text(command),
        "exit_code": completed.returncode,
        "test_summaries": len(summaries),
        "passed_summaries": passed,
        "failed_summaries": failed,
        "tests_executed": executed,
        "log": str(log_path.relative_to(ROOT)),
    }


def write_report(report: dict[str, object]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def candidate_contract(evidence_head: str) -> tuple[bool, dict[str, object]]:
    """Validate the production baseline and evidence-only descendant contract."""
    ancestor_check = subprocess.run(
        ["git", "merge-base", "--is-ancestor", EXPECTED_CANDIDATE, evidence_head],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    is_ancestor = ancestor_check.returncode == 0
    diff_output = subprocess.run(
        ["git", "diff", "--name-only", EXPECTED_CANDIDATE, evidence_head],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    diff_paths = sorted(
        {line.strip() for line in diff_output.stdout.splitlines() if line.strip()}
    )
    forbidden_paths = sorted(set(diff_paths) - AUTHORIZED_T24_PATHS)
    contract = {
        "candidate_sha": EXPECTED_CANDIDATE,
        "base_sha": EXPECTED_CANDIDATE,
        "evidence_head": evidence_head,
        "evidence_head_is_ancestor_descendant": is_ancestor,
        "candidate_diff_paths": diff_paths,
        "authorized_candidate_diff_paths": sorted(AUTHORIZED_T24_PATHS),
        "forbidden_candidate_diff_paths": forbidden_paths,
    }
    if ancestor_check.returncode not in {0, 1}:
        contract["failure"] = "unable to establish fixed candidate ancestry"
        return False, contract
    if diff_output.returncode != 0:
        contract["failure"] = "unable to inspect complete candidate diff"
        return False, contract
    if not is_ancestor:
        contract["failure"] = "fixed production candidate is not an ancestor of evidence head"
        return False, contract
    if forbidden_paths:
        contract["failure"] = "candidate diff contains files outside authorized T24 evidence-only paths"
        return False, contract
    contract["candidate_kind"] = (
        "fixed-production-baseline"
        if evidence_head == EXPECTED_CANDIDATE
        else "evidence-only-descendant"
    )
    return True, contract


def main() -> int:
    evidence_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    candidate_ok, contract = candidate_contract(evidence_head)
    rows = parse_manifest()
    manifest_ids = sorted({item for row in rows for item in row["cv_ids"]}, key=lambda value: int(value[3:]))
    expected_ids = sorted(COMPLETED_CV_IDS + [f"CV-{number:03d}" for number in [17, 18, 19, 28, 29, 34, 35, 36, 37]], key=lambda value: int(value[3:]))
    if manifest_ids != expected_ids:
        raise RuntimeError(f"T22 CV set mismatch: expected {expected_ids}, found {manifest_ids}")
    if not candidate_ok:
        report = {
            "schema_version": 1,
            "type": "loom-validator.certification-gate",
            "gate": "VALR-T24",
            **contract,
            "candidate_discipline": "fixed production baseline or evidence-only descendant with authorized T24-only diff",
            "gate_passes": False,
        }
        write_report(report)
        print(f"T24 candidate contract mismatch: {contract['failure']}", file=sys.stderr)
        return 2

    command_results: dict[str, dict[str, object]] = {}
    for name, command in TEST_TARGETS.items():
        print(f"T24 running {command_text(command)}", flush=True)
        command_results[name] = run_command(name, command)

    evidence_rows: list[dict[str, object]] = []
    for row in rows:
        status = str(row["status"])
        suite = suite_for(row)
        command_id = "validator_pg18" if row["pg18_required"] else suite
        command_result = command_results[command_id]
        if status == "ready":
            outcome = "Pass" if command_result["tests_executed"] and command_result["exit_code"] == 0 else "Fail"
            needs_postgres_evidence = row["pg18_required"] or "live pg" in str(row["pg_requirement"]).lower()
            evidence_class = "postgresql" if needs_postgres_evidence else "in-memory"
            prerequisite = "satisfied" if outcome == "Pass" else "command did not produce an all-passing executed test summary"
        elif status == "gap":
            outcome = "Unavailable"
            evidence_class = "none"
            prerequisite = "T22 manifest gap: no trusted Validator evidence exists"
        else:
            outcome = "Pass"
            evidence_class = "core-or-transport"
            prerequisite = "intentionally non-Validator-covered contract"
        for cv_id in row["cv_ids"]:
            evidence_rows.append(
                {
                    "cv_id": cv_id,
                    "candidate_sha": EXPECTED_CANDIDATE,
                    "evidence_head": evidence_head,
                    "outcome": outcome,
                    "manifest_status": status,
                    "trusted_evidence_class": evidence_class,
                    "restart_required": row["restart_required"],
                    "pg18_required": row["pg18_required"],
                    "prerequisite": prerequisite,
                    "exact_command": row["required_command"],
                    "executed_command_id": command_id,
                    "tests_executed": command_result["tests_executed"],
                    "evidence_log": command_result["log"],
                    "reason": row["reason"],
                }
            )
    evidence_rows.sort(key=lambda row: row["cv_id"])
    unique_ids = [row["cv_id"] for row in evidence_rows]
    report = {
        "schema_version": 1,
        "type": "loom-validator.certification-gate",
        "gate": "VALR-T24",
        "candidate_sha": EXPECTED_CANDIDATE,
        "base_sha": EXPECTED_CANDIDATE,
        "evidence_head": evidence_head,
        "candidate_discipline": "fixed production baseline or evidence-only descendant with authorized T24-only diff",
        "candidate_contract": contract,
        "race_protocol": "closed",
        "commands": [command_results[name] for name in sorted(command_results)],
        "registry": {
            "completed_cv_ids": COMPLETED_CV_IDS,
            "completed_cv_count": len(COMPLETED_CV_IDS),
            "manifest_cv_count": len(unique_ids),
            "duplicate_free": len(unique_ids) == len(set(unique_ids)),
            "deterministic_order": unique_ids == sorted(unique_ids, key=lambda value: int(value[3:])),
        },
        "rows": evidence_rows,
        "manifest_gap_count": sum(1 for row in evidence_rows if row["manifest_status"] == "gap"),
        "gate_passes": (
            len(unique_ids) == len(set(unique_ids))
            and all(row["outcome"] == "Pass" for row in evidence_rows)
            and all(result["tests_executed"] and result["exit_code"] == 0 for result in command_results.values())
        ),
    }
    write_report(report)
    print(f"T24 Validator certification report: {REPORT}")
    print(json.dumps({"gate_passes": report["gate_passes"], "rows": len(evidence_rows), "manifest_gaps": report["manifest_gap_count"]}, sort_keys=True))
    return 0 if report["gate_passes"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        print(f"T24 certification gate error: {error}", file=sys.stderr)
        raise SystemExit(2)
