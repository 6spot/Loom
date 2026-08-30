#!/usr/bin/env python3
"""Run the fail-closed current-main Validator certification gate.

The gate is an evidence collector, not a second Validator. It consumes the
merged T22 manifest, runs the named public-consumer integration targets plus
the controlled PostgreSQL 18 live gate, and joins only real executed test
summaries into a deterministic 40-row report.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = "docs/tasks/validator-recert/stage-3/t22-certification-manifest.md"
PRODUCTION_CANDIDATE = os.environ.get(
    "LOOM_CERTIFICATION_CANDIDATE",
    "02c55a6b5c34f227abfcb732a21bf6c390e22578",
)
MANIFEST_REF = os.environ.get("LOOM_T22_MANIFEST_REF", "origin/main")
REPORT = Path(
    os.environ.get(
        "LOOM_T24_REPORT_PATH",
        ROOT / "target/validator/t24-validator-certification-gate.json",
    )
)
LOG_DIR = REPORT.parent / "t24-logs"
T24_PG_DATABASE = "loom_t24_certification"

EXPECTED_CV_IDS = [f"CV-{number:03d}" for number in range(1, 41)]
T20_REQUIRED_CV_IDS = {
    "CV-014",
    "CV-016",
    "CV-022",
    "CV-023",
    "CV-030",
    "CV-031",
    "CV-032",
    "CV-033",
    "CV-039",
    "CV-040",
}

# Evidence-only descendants may update documentation and the mechanics that
# execute/record this certification. Production/runtime/validator semantics are
# deliberately absent from this allowlist.
AUTHORIZED_NON_DOC_PATHS = {
    ".github/workflows/ci.yml",
    "tools/validator-certification-gate.py",
    "tools/validator-certification-gate.sh",
}

TEST_TARGETS: dict[str, list[str]] = {
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


def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, check=False, **kwargs)


def ensure_main_history() -> None:
    """Fetch enough main history to prove candidate ancestry in shallow CI."""
    completed = run(
        ["git", "fetch", "--no-tags", "origin", "main", "--depth=100"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"unable to fetch main history:\n{completed.stdout}")


def command_text(command: list[str]) -> str:
    return " ".join(command)


def split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def cv_ids(cell: str) -> list[str]:
    ids: set[str] = set()
    for part in cell.split(";"):
        selector = part.strip().replace("`", "")
        if not selector.startswith("CV-"):
            continue
        for start, end in re.findall(r"CV-(\d{3})(?:\.\.CV-(\d{3}))?", selector):
            first = int(start)
            last = int(end or start)
            ids.update(f"CV-{number:03d}" for number in range(first, last + 1))
    return sorted(ids, key=lambda value: int(value[3:]))


def manifest_text() -> str:
    completed = run(
        ["git", "show", f"{MANIFEST_REF}:{MANIFEST_PATH}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"unable to read merged T22 manifest {MANIFEST_REF}:{MANIFEST_PATH}: "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout


def manifest_identity() -> dict[str, str]:
    completed = run(
        ["git", "rev-parse", MANIFEST_REF],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"unable to resolve manifest ref {MANIFEST_REF}")
    return {
        "ref": MANIFEST_REF,
        "commit": completed.stdout.strip(),
        "path": MANIFEST_PATH,
    }


def suite_for(row: dict[str, object]) -> str:
    required_command = str(row.get("required_command", ""))
    match = re.search(r"(?:^|\s)--test(?:=|\s+)([A-Za-z0-9_-]+)", required_command)
    if match:
        return match.group(1)
    validator = str(row.get("validator", ""))
    match = re.search(r"apps/loom-validator/tests/([^:]+)\.rs", validator)
    if match:
        return match.group(1)
    return "validator_lib"


def parse_manifest() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in manifest_text().splitlines():
        if not line.startswith("|"):
            continue
        cells = split_row(line)
        if len(cells) != 9 or cells[0] in {"Capability", "---"}:
            continue
        ids = [] if cells[2].startswith("No separate public Validator CV") else cv_ids(cells[2])
        status_match = re.search(
            r"`(ready|gap|intentionally non-Validator-covered)`", cells[7]
        )
        if not status_match:
            continue
        rows.append(
            {
                "capability": cells[0],
                "validator": cells[2],
                "pg_requirement": cells[4],
                "restart_requirement": cells[5],
                "required_command": cells[6],
                "status": status_match.group(1),
                "reason": cells[7],
                "cv_ids": ids,
                "suite": suite_for(
                    {
                        "required_command": cells[6],
                        "validator": cells[2],
                    }
                ),
            }
        )
    if not rows:
        raise RuntimeError(f"no certification rows found in {MANIFEST_PATH}")
    return rows


def authorized_evidence_path(path: str) -> bool:
    return path.startswith("docs/") or path.endswith(".md") or path in AUTHORIZED_NON_DOC_PATHS


def candidate_contract(evidence_head: str) -> tuple[bool, dict[str, object]]:
    ancestry = run(
        ["git", "merge-base", "--is-ancestor", PRODUCTION_CANDIDATE, evidence_head],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    diff = run(
        ["git", "diff", "--name-only", PRODUCTION_CANDIDATE, evidence_head],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    diff_paths = sorted({line.strip() for line in diff.stdout.splitlines() if line.strip()})
    forbidden = [path for path in diff_paths if not authorized_evidence_path(path)]
    contract: dict[str, object] = {
        "candidate_sha": PRODUCTION_CANDIDATE,
        "evidence_head": evidence_head,
        "candidate_is_ancestor": ancestry.returncode == 0,
        "candidate_diff_paths": diff_paths,
        "forbidden_candidate_diff_paths": forbidden,
    }
    if ancestry.returncode not in {0, 1}:
        contract["failure"] = "unable to establish production-candidate ancestry"
        return False, contract
    if ancestry.returncode != 0:
        contract["failure"] = "production candidate is not an ancestor of evidence HEAD"
        return False, contract
    if diff.returncode != 0:
        contract["failure"] = "unable to inspect production-candidate diff"
        return False, contract
    if forbidden:
        contract["failure"] = "evidence descendant contains production-changing paths"
        return False, contract
    contract["candidate_kind"] = (
        "exact-production-candidate"
        if evidence_head == PRODUCTION_CANDIDATE
        else "evidence-only-descendant"
    )
    return True, contract


def prepare_t24_pg_database(env: dict[str, str]) -> tuple[bool, str]:
    service = run(
        ["bash", "tools/postgres-test.sh", "up"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = service.stdout
    if service.returncode != 0:
        return False, output
    reset = run(
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
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return reset.returncode == 0, output + reset.stdout


def run_command(name: str, command: list[str]) -> dict[str, object]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    preparation = ""
    if name == "validator_pg18":
        ok, preparation = prepare_t24_pg_database(env)
        if not ok:
            log_path = LOG_DIR / f"{name}.log"
            log_path.write_text(preparation, encoding="utf-8")
            return {
                "command_id": name,
                "command": command_text(command),
                "exit_code": 1,
                "test_summaries": 0,
                "passed_summaries": 0,
                "failed_summaries": 0,
                "tests_executed": False,
                "preparation_failed": True,
                "log": str(log_path.relative_to(ROOT)),
            }
        env["LOOM_TEST_POSTGRES_URL"] = (
            f"postgresql://loom:loom@127.0.0.1:15432/{T24_PG_DATABASE}"
        )

    completed = run(
        command,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = preparation + completed.stdout
    log_path = LOG_DIR / f"{name}.log"
    log_path.write_text(output, encoding="utf-8")
    summaries = re.findall(r"test result: (ok|FAILED)\.\s+(.+)", output)
    passed = sum(1 for state, _ in summaries if state == "ok")
    failed = sum(1 for state, _ in summaries if state == "FAILED")
    tests_executed = bool(summaries) and all(
        state == "ok" and re.search(r"\b[1-9]\d* passed\b", detail) is not None
        for state, detail in summaries
    )
    if name == "validator_pg18":
        tests_executed = tests_executed and "T20 PostgreSQL live matrix:" in output
    return {
        "command_id": name,
        "command": command_text(command),
        "exit_code": completed.returncode,
        "test_summaries": len(summaries),
        "passed_summaries": passed,
        "failed_summaries": failed,
        "tests_executed": tests_executed,
        "log": str(log_path.relative_to(ROOT)),
    }


def result_passes(result: dict[str, object]) -> bool:
    return bool(result["tests_executed"]) and int(result["exit_code"]) == 0


def write_report(report: dict[str, object]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def regression_check() -> int:
    ensure_main_history()
    rows = parse_manifest()
    ids = sorted(
        {cv for row in rows for cv in row["cv_ids"]},
        key=lambda value: int(value[3:]),
    )
    assert ids == EXPECTED_CV_IDS, (ids, EXPECTED_CV_IDS)
    assert authorized_evidence_path("docs/tasks/validator-recert/stage-3/t25-final-certificate.md")
    assert authorized_evidence_path(".github/workflows/ci.yml")
    assert not authorized_evidence_path("crates/loom-runtime/src/orchestration.rs")
    semantic_rows = [row for row in rows if "CV-028" in row["cv_ids"]]
    assert len(semantic_rows) == 1
    assert semantic_rows[0]["status"] == "ready"
    assert semantic_rows[0]["suite"] == "semantic_blob"
    print("T24 regression checks PASS: exact 40-CV manifest and evidence-only candidate fence")
    return 0


def main() -> int:
    ensure_main_history()
    evidence_head = run(
        ["git", "rev-parse", "HEAD"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ).stdout.strip()
    candidate_ok, contract = candidate_contract(evidence_head)
    rows = parse_manifest()
    manifest_ids = sorted(
        [cv for row in rows for cv in row["cv_ids"]],
        key=lambda value: int(value[3:]),
    )
    if manifest_ids != EXPECTED_CV_IDS:
        raise RuntimeError(
            f"T22 CV set mismatch: expected {EXPECTED_CV_IDS}, found {manifest_ids}"
        )

    if not candidate_ok:
        report = {
            "schema_version": 2,
            "type": "loom-validator.certification-gate",
            "gate": "VALR-T24",
            "candidate_sha": PRODUCTION_CANDIDATE,
            "evidence_head": evidence_head,
            "candidate_contract": contract,
            "manifest": manifest_identity(),
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
        suite = str(row["suite"])
        suite_result = command_results[suite]
        for cv_id in row["cv_ids"]:
            t20_required = cv_id in T20_REQUIRED_CV_IDS
            suite_ok = result_passes(suite_result)
            pg18_ok = result_passes(command_results["validator_pg18"])
            if status == "ready":
                outcome = "Pass" if suite_ok and (not t20_required or pg18_ok) else "Fail"
                prerequisite = (
                    "satisfied"
                    if outcome == "Pass"
                    else "required executed suite or PostgreSQL 18 evidence did not pass"
                )
            elif status == "gap":
                outcome = "Unavailable"
                prerequisite = "T22 manifest gap: trusted certification evidence is absent"
            else:
                outcome = "Pass"
                prerequisite = "intentionally non-Validator-covered static contract"
            evidence_class = (
                "postgresql+public-client"
                if outcome == "Pass" and (t20_required or cv_id in {"CV-004", "CV-028", "CV-029"})
                else "public-client"
                if outcome == "Pass"
                else "none"
            )
            evidence_rows.append(
                {
                    "cv_id": cv_id,
                    "candidate_sha": PRODUCTION_CANDIDATE,
                    "evidence_head": evidence_head,
                    "manifest_status": status,
                    "outcome": outcome,
                    "trusted_evidence_class": evidence_class,
                    "suite": suite,
                    "suite_tests_executed": suite_result["tests_executed"],
                    "suite_exit_code": suite_result["exit_code"],
                    "t20_pg18_required": t20_required,
                    "t20_pg18_passed": pg18_ok,
                    "prerequisite": prerequisite,
                    "exact_command": row["required_command"],
                    "evidence_log": suite_result["log"],
                    "reason": row["reason"],
                }
            )

    evidence_rows.sort(key=lambda item: int(str(item["cv_id"])[3:]))
    unique_ids = [str(row["cv_id"]) for row in evidence_rows]
    manifest_gap_count = sum(1 for row in evidence_rows if row["manifest_status"] == "gap")
    pass_count = sum(1 for row in evidence_rows if row["outcome"] == "Pass")
    fail_count = sum(1 for row in evidence_rows if row["outcome"] == "Fail")
    unavailable_count = sum(1 for row in evidence_rows if row["outcome"] == "Unavailable")
    all_commands_pass = all(result_passes(result) for result in command_results.values())
    gate_passes = (
        unique_ids == EXPECTED_CV_IDS
        and len(unique_ids) == len(set(unique_ids))
        and manifest_gap_count == 0
        and pass_count == 40
        and fail_count == 0
        and unavailable_count == 0
        and all_commands_pass
    )

    report = {
        "schema_version": 2,
        "type": "loom-validator.certification-gate",
        "gate": "VALR-T24",
        "candidate_sha": PRODUCTION_CANDIDATE,
        "evidence_head": evidence_head,
        "candidate_contract": contract,
        "manifest": manifest_identity(),
        "commands": [command_results[name] for name in sorted(command_results)],
        "registry": {
            "expected_cv_ids": EXPECTED_CV_IDS,
            "manifest_cv_count": len(unique_ids),
            "duplicate_free": len(unique_ids) == len(set(unique_ids)),
            "deterministic_order": unique_ids == EXPECTED_CV_IDS,
        },
        "rows": evidence_rows,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "unavailable_count": unavailable_count,
        "manifest_gap_count": manifest_gap_count,
        "all_commands_pass": all_commands_pass,
        "gate_passes": gate_passes,
    }
    write_report(report)
    print(f"T24 Validator certification report: {REPORT}")
    print(
        json.dumps(
            {
                "gate_passes": gate_passes,
                "rows": len(evidence_rows),
                "pass": pass_count,
                "fail": fail_count,
                "unavailable": unavailable_count,
                "manifest_gaps": manifest_gap_count,
            },
            sort_keys=True,
        )
    )
    return 0 if gate_passes else 1


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--regression-check"]:
            raise SystemExit(regression_check())
        if sys.argv[1:]:
            raise RuntimeError(f"unsupported arguments: {sys.argv[1:]}")
        raise SystemExit(main())
    except (AssertionError, OSError, subprocess.SubprocessError, RuntimeError) as error:
        print(f"T24 certification gate error: {error}", file=sys.stderr)
        raise SystemExit(2)
