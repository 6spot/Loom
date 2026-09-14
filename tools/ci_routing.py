#!/usr/bin/env python3
"""One path classifier and fail-closed result contract for repository CI."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit


GROUPS = {
    "repository": (
        "routing-tests", "documentation", "ledger", "dependency-policy", "rust",
        "deployment", "chronicle-static", "chronicle-first-round",
        "chronicle-third-round", "chronicle",
    ),
    "chronicle": (
        "offline-gate", "chapter-pipeline", "reading-contracts",
        "person-contracts", "web-components", "second-round-gate",
        "third-round-gate",
    ),
    "validator": ("validator-ledger", "validator-static"),
}
JOBS = tuple(job for group in GROUPS.values() for job in group)
STEPS = (
    "active_docs", "chronicle_python", "chronicle_rust", "chronicle_web",
    "chronicle_deployment", "chronicle_corpus", "chronicle_contract",
    "chronicle_first_round", "chronicle_third_round",
)
SUITES = ("studio", "narrative", "reading", "history", "person")
CI_FILES = {
    "tools/ci_routing.py", "tools/test_ci_routing.py",
    "tools/requirements-ci.txt", ".github/CODEOWNERS",
}
WEB = "apps/chronicle/webapp/"
DIST = "apps/chronicle/web/dist/"
CHRONICLE = "apps/chronicle/"


def clean_path(path: str) -> str:
    if not isinstance(path, str):
        raise ValueError("repository paths must be strings")
    path = path.removeprefix("./")
    if not path or path.startswith("/") or ".." in PurePosixPath(path).parts:
        raise ValueError(f"invalid repository path: {path!r}")
    return path


def ordinary_doc(path: str) -> bool:
    """Runtime inputs and acceptance contracts are classified before this."""
    name = PurePosixPath(path).name
    return (
        name in {"AGENTS.md", "README.md", "LICENSE", "LICENSE.md"}
        or path.startswith(("docs/", ".agents/skills/"))
        and path.endswith((".md", ".rst", ".txt"))
        or path.startswith(CHRONICLE + "docs/") and path.endswith(".md")
    )


def classify(paths: list[str], *, full: bool = False) -> dict:
    paths = sorted({clean_path(path) for path in paths})
    plan = {
        "version": 1,
        "jobs": dict.fromkeys(JOBS, False),
        "steps": dict.fromkeys(STEPS, False),
        "suites": dict.fromkeys(SUITES, False),
        "paths": paths,
        "docs": [],
        "first_round_notes": [],
        "third_round_notes": [],
        "reasons": {job: [] for job in JOBS},
    }

    def enable(*jobs: str, why: str) -> None:
        for job in jobs:
            plan["jobs"][job] = True
            if why not in plan["reasons"][job]:
                plan["reasons"][job].append(why)

    def step(*names: str) -> None:
        for name in names:
            plan["steps"][name] = True

    def components(*suites: str, why: str) -> None:
        enable("web-components", why=why)
        for suite in suites:
            plan["suites"][suite] = True

    def frontend(*suites: str, why: str, public: bool = False) -> None:
        enable("chronicle-static", why=why)
        step("chronicle_web")
        components(*suites, why=why)
        if public:
            if "reading" in suites:
                enable("second-round-gate", why=why)
            if "history" in suites or "person" in suites:
                enable("third-round-gate", why=why)

    def all_chronicle(why: str) -> None:
        enable("chronicle-static", "chronicle-first-round",
               *GROUPS["chronicle"], why=why)
        step("chronicle_python", "chronicle_rust", "chronicle_web",
             "chronicle_deployment", "chronicle_corpus", "chronicle_contract")
        components(*SUITES, why=why)

    def backend(domain: str, why: str) -> None:
        enable("chronicle-static", why=why)
        step("chronicle_python")
        if domain == "chapter":
            enable("offline-gate", "chapter-pipeline", "second-round-gate",
                   "third-round-gate", why=why)
        elif domain == "reading":
            enable("reading-contracts", "second-round-gate",
                   "third-round-gate", why=why)
        elif domain == "person":
            enable("person-contracts", "third-round-gate", why=why)
        else:
            all_chronicle(why)

    enable("routing-tests", why="CI routing and workflow wiring are always checked")
    # A normal source rebuild changes committed assets too. Route by source,
    # then let the build job verify every committed asset against that source.
    # Asset-only edits must instead exercise the entire frontend.
    has_web_source = any(
        p.startswith(WEB + "src/")
        or p in {WEB + name for name in (
            "package.json", "package-lock.json", "vite.config.ts",
            "tsconfig.json", "tsconfig.node.json", "index.html",
        )}
        for p in paths
    )

    for path in paths:
        name = PurePosixPath(path).name
        why = path
        if path in CI_FILES or path == ".github/workflows/ci.yml":
            full = True
        elif path == ".github/workflows/chronicle.yml":
            all_chronicle(why)
        elif path == ".github/workflows/validator.yml":
            enable(*GROUPS["validator"], why=why)
        elif path.startswith("docs/tasks/chronicle/first-round/") and path.endswith(".md"):
            enable("documentation", "chronicle-first-round", why=why)
            step("chronicle_first_round")
            plan["first_round_notes"].append(path)
            plan["docs"].append(path)
        elif path.startswith("docs/tasks/chronicle/third-round/") and path.endswith(".md"):
            enable("documentation", "chronicle-third-round", why=why)
            step("chronicle_third_round")
            plan["third_round_notes"].append(path)
            plan["docs"].append(path)
        elif path.startswith(("docs/tasks/scheduler-discovery/", "docs/tasks/ci-governance/")):
            enable("documentation", "ledger", why=why)
            if path.endswith(".md"):
                plan["docs"].append(path)
        elif path.startswith(("docs/tasks/validator/", "docs/tasks/validator-recert/")):
            enable("documentation", "validator-ledger", why=why)
            if path.endswith(".md"):
                plan["docs"].append(path)
        elif path.startswith("tools/fixtures/validator-ready/") or path in {
            "tools/validator_ready.py", "tools/test_validator_ready.py",
        }:
            enable("ledger", "validator-ledger", why=why)
        # Corpus, prompts, schemas and fixture inputs are executable contracts,
        # even when their extension is Markdown or plain text.
        elif path.startswith((CHRONICLE + "corpus/", CHRONICLE + "ingestion/fixtures/")):
            enable("chronicle-first-round", why=why)
            step("chronicle_corpus")
            if "/third-round/" in path:
                backend("person", why)
            elif "/reading-enhancement/" in path or name == "test_corroboration_cases.py":
                backend("reading", why)
            else:
                backend("chapter", why)
        elif path.startswith(CHRONICLE + "ingestion/schemas/"):
            all_chronicle(why)
        elif path.startswith((CHRONICLE + "worker/config/", CHRONICLE + "ingestion/config/")):
            backend("chapter", why)
        elif path.startswith(CHRONICLE + "docs/") and name in {
            "chapter-acceptance.md", "reading-acceptance.md",
            "person-state-acceptance.md", "final-acceptance.md",
        }:
            enable("documentation", why=why)
            plan["docs"].append(path)
            if name == "reading-acceptance.md":
                backend("reading", why)
            elif name == "person-state-acceptance.md":
                backend("person", why)
            else:
                backend("chapter", why)
        elif ordinary_doc(path):
            enable("documentation", why=why)
            if path.endswith(".md"):
                plan["docs"].append(path)
            if path in {"README.md", "docs/quickstart.md", "docs/operator-guide.md"}:
                step("active_docs")
        elif path.startswith("apps/loom-validator/"):
            enable("validator-static", why=why)
            if name == "Cargo.toml":
                enable("dependency-policy", why=why)
        elif path in {"Cargo.toml", "Cargo.lock", "rust-toolchain.toml"}:
            enable("rust", "dependency-policy", "validator-static", why=why)
        elif path.startswith((CHRONICLE + "server/", CHRONICLE + "control_plane/")):
            all_chronicle(why)
        elif path in {"compose.chronicle.yaml", ".env.chronicle.example", CHRONICLE + "Dockerfile"}:
            all_chronicle(why)
        elif path.startswith(DIST):
            enable("chronicle-static", why=why)
            step("chronicle_web")
            if not has_web_source:
                frontend(*SUITES, why="asset-only edit: " + path, public=True)
        elif path.startswith(WEB):
            relative = path[len(WEB):]
            if relative in {
                "src/components/reading/ReadingContextPanel.tsx",
                "src/lib/reading-types.ts", "src/lib/reading-api.ts",
                "src/lib/reading-history.ts", "src/lib/reading-location.ts",
                "src/styles/reading-layout.css", "src/styles/reading-context.css",
                "src/styles/public-reading.css",
            }:
                # Also consumed by HistoryPage/EntityPage, not only /read.
                frontend("reading", "history", "person", why=why, public=True)
            elif (
                relative.startswith(("src/components/studio/", "src/components/ui/", "src/pages/studio/"))
                or relative.startswith(("src/lib/studio-", "src/lib/review-", "src/lib/chapter-content-review"))
                or name in {
                    "studio.css", "review-evidence.css", "chapter-content-review.css",
                    "studio-workspace-component-smoke.mjs", "narrative-review-component-smoke.mjs",
                }
                or relative.startswith("tests/studio-")
            ):
                frontend("studio", "narrative", "person", why=why)
            elif "person-state" in relative.lower() or name.startswith("PersonState") or name == "EntityPage.tsx":
                frontend("person", why=why, public=True)
            elif "history" in relative.lower() or "narrative" in relative.lower() or name == "HomePage.tsx":
                frontend("history", "narrative", why=why, public=True)
            elif (
                relative.startswith(("src/components/reading/", "src/lib/reading-", "src/pages/public/Reading"))
                or name.startswith("reading-") and "component-smoke" not in name
            ):
                frontend("reading", why=why, public=True)
            else:
                # Shared controller, auth/API client, styles, entry points,
                # dependencies, harnesses and new unclassified frontend files.
                frontend(*SUITES, why="shared/unclassified frontend: " + path, public=True)
        elif path.startswith(CHRONICLE + "web/"):
            frontend(*SUITES, why=why, public=True)
        elif path.startswith(CHRONICLE + "acceptance/"):
            if name in {"first_round_gate.py", "test_first_round_gate.py"}:
                enable("offline-gate", why=why)
            elif name in {"third_round_gate.py", "test_third_round_gate.py"}:
                enable("third-round-gate", why=why)
            elif name in {"second_round_gate.py", "test_second_round_gate.py", "reading_scale_fixture.py"}:
                # R3 imports helpers from R2; changes affect both gates.
                enable("second-round-gate", "third-round-gate", why=why)
            else:
                all_chronicle(why)
        elif path.startswith((CHRONICLE + "persistence/", CHRONICLE + "worker/", CHRONICLE + "read_api/")):
            if "/migrations/" in path or name in {
                "migrations.py", "common.py", "chronicle_persist.py", "postgres_v0.py",
                "requirements.txt", "router.py", "server.py", "repository.py", "read_common.py",
                "chapter_contract.py", "staged_chapter_contract.py", "chapter_models.py",
                "extraction_model_schema.py", "fixture_model.py",
            }:
                all_chronicle(why)
            elif "person_state" in name or name.startswith("reading_people"):
                backend("person", why)
            elif "narrative" in name or "reading" in name or name in {"history.py", "reader_language.py", "search.py"}:
                backend("reading", why)
            elif any(token in name for token in ("chapter", "staged", "model_provider", "studio_jobs", "studio_documents", "production", "segmentation", "extraction")):
                backend("chapter", why)
            else:
                all_chronicle("unclassified/shared backend: " + path)
        elif path.startswith(CHRONICLE):
            all_chronicle("unclassified Chronicle file: " + path)
        elif path.endswith("/Cargo.toml") or path == "deny.toml":
            enable("rust", "dependency-policy", why=why)
        elif path.endswith(".rs") or path.startswith(("crates/", "capabilities/", "tests/")) or path in {
            "rustfmt.toml", "tools/check_architecture.py", "tools/check_storage_sql_ownership.py",
        }:
            enable("rust", why=why)
        elif path in {"compose.yaml", "Dockerfile", ".dockerignore", ".env.example", "compose.test-db.yaml"} or path.startswith("docker/"):
            enable("deployment", why=why)
            if path == ".dockerignore":
                all_chronicle(why)
        else:
            full = True
            why = "unclassified repository file: " + path
            for job in JOBS:
                enable(job, why=why)

    if full:
        enable(*JOBS, why="manual full run or CI policy/shared routing change")
        step(*STEPS)
        components(*SUITES, why="full run")
    if any(plan["jobs"][job] for job in GROUPS["chronicle"]):
        enable("chronicle", why="selected Chronicle checks must reach Repository Gate")
    return plan


def validate_plan(plan: dict) -> None:
    if plan.get("version") != 1:
        raise ValueError("missing/unsupported routing plan version")
    for field, keys in (("jobs", JOBS), ("steps", STEPS), ("suites", SUITES)):
        values = plan.get(field)
        if not isinstance(values, dict) or set(values) != set(keys):
            raise ValueError(f"invalid {field} keys")
        if any(type(value) is not bool for value in values.values()):
            raise ValueError(f"{field} values must be booleans")
    for field in ("paths", "docs", "first_round_notes", "third_round_notes"):
        if not isinstance(plan.get(field), list):
            raise ValueError(f"missing {field}")
        for path in plan[field]:
            clean_path(path)
    if plan["jobs"]["chronicle"] != any(plan["jobs"][job] for job in GROUPS["chronicle"]):
        raise ValueError("Chronicle caller and selected checks disagree")


def check_results(plan: dict, needs: dict, group: str) -> list[str]:
    validate_plan(plan)
    errors = []
    if needs.get("changes", {}).get("result") != "success":
        errors.append("changes must succeed")
    for job in GROUPS[group]:
        result = needs.get(job, {}).get("result")
        if plan["jobs"][job]:
            if result != "success":
                errors.append(f"selected {job}: expected success, got {result!r}")
        elif result not in {"success", "skipped"}:
            errors.append(f"unselected {job}: expected skipped/success, got {result!r}")
    return errors


def changed_paths(event_name: str, event: dict) -> list[str]:
    def git(*args: str, input: str | None = None) -> str:
        return subprocess.check_output(["git", *args], input=input, text=True).strip()

    if event_name == "workflow_dispatch":
        return []
    if event_name == "pull_request":
        base = event["pull_request"]["base"]["sha"]
        head = event["pull_request"]["head"]["sha"]
        base = git("merge-base", base, head)
    elif event_name == "push":
        base, head = event["before"], event["after"]
        if not base or set(base) == {"0"}:
            base = git("hash-object", "-t", "tree", "--stdin", input="")
    else:
        raise ValueError(f"unsupported event: {event_name}")
    # No rename detection: both old and new owners receive a deletion/addition.
    output = subprocess.check_output(
        ["git", "diff", "--no-renames", "--name-only", "-z", base, head]
    )
    return [p.decode("utf-8") for p in output.split(b"\0") if p]


def check_docs(plan: dict) -> None:
    for name in plan["docs"]:
        path = Path(name)
        if not path.exists():  # A deleted document has no new contents to check.
            continue
        lines = []
        fence = None
        for line in path.read_text(encoding="utf-8").splitlines():
            marker = re.match(r"^ {0,3}(" + chr(96) + r"{3,}|~{3,})", line)
            if marker:
                token = marker.group(1)
                if fence is None:
                    fence = token
                elif token[0] == fence[0] and len(token) >= len(fence):
                    fence = None
                continue
            if fence is None:
                lines.append(line)
        text = "\n".join(lines)
        for target in re.findall(r"\[[^\]]+\]\(([^)\s]+)\)", text):
            url = urlsplit(target.strip("<>"))
            if url.scheme or not url.path or url.path.startswith("/"):
                continue
            # Ignore illustrative wildcard paths, but verify real relative files.
            if any(char in url.path for char in "*{}"):
                continue
            if not (path.parent / unquote(url.path)).exists():
                raise ValueError(f"{name}: missing link target {target}")
        print(f"document links OK: {name}")


def check_notes(plan: dict, round_name: str) -> None:
    prefix = {"first": "C2-R1-", "third": "C2-R3-"}[round_name]
    for name in plan[round_name + "_round_notes"]:
        note = Path(name)
        if not note.exists():
            continue
        text = note.read_text(encoding="utf-8")
        match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
        if not match:
            raise ValueError(f"{note}: missing YAML front matter")
        front = match.group(1)
        for key in ("task", "issue", "kind"):
            if not re.search(rf"^{key}:\s+\S+", front, re.MULTILINE):
                raise ValueError(f"{note}: missing {key}")
        task = re.search(r"^task:\s*(\S+)", front, re.MULTILINE).group(1)
        if note.stem.startswith("T") and task != prefix + note.stem.split("-", 1)[0]:
            raise ValueError(f"{note}: task does not match filename")
        print(f"note OK: {note}")


def emit(plan: dict, output: str | None, summary: str | None) -> None:
    validate_plan(plan)
    encoded = json.dumps(plan, ensure_ascii=True, separators=(",", ":"))
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("plan=" + encoded + "\n")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## CI selection\n\n| Check | Selected | Reason |\n| --- | --- | --- |\n")
            for job, selected in plan["jobs"].items():
                reasons = plan["reasons"].get(job, [])[:6]
                reason = "; ".join(reasons) if selected else "No affected contract"
                reason = reason.replace("|", r"\|").replace("\n", " ")
                handle.write(f"| {job} | {str(selected).lower()} | {reason} |\n")
    print(encoded)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("classify", "gate", "docs", "notes"))
    parser.add_argument("--event", default=os.getenv("GITHUB_EVENT_NAME"))
    parser.add_argument("--event-path", default=os.getenv("GITHUB_EVENT_PATH"))
    parser.add_argument("--paths", nargs="*")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--plan-json", default=os.getenv("CI_PLAN"))
    parser.add_argument("--needs-json", default=os.getenv("CI_NEEDS"))
    parser.add_argument("--group", choices=GROUPS)
    parser.add_argument("--round", choices=("first", "third"))
    parser.add_argument("--github-output")
    parser.add_argument("--summary")
    args = parser.parse_args()
    if args.command == "classify":
        if args.plan_json:
            plan = json.loads(args.plan_json)
        else:
            if args.paths is not None:
                paths = args.paths
            elif args.event_path:
                paths = changed_paths(args.event, json.loads(Path(args.event_path).read_text()))
            elif args.all:
                paths = []
            else:
                raise ValueError("provide --paths, --all or a GitHub event")
            plan = classify(paths, full=args.all or args.event == "workflow_dispatch")
        emit(plan, args.github_output, args.summary)
    else:
        plan = json.loads(args.plan_json or "")
        validate_plan(plan)
        if args.command == "gate":
            if not args.group:
                raise ValueError("gate requires --group")
            errors = check_results(plan, json.loads(args.needs_json or ""), args.group)
            if errors:
                raise ValueError("; ".join(errors))
            print(f"{args.group}: all selected checks succeeded")
        elif args.command == "docs":
            check_docs(plan)
        else:
            if not args.round:
                raise ValueError("notes requires --round")
            check_notes(plan, args.round)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as error:
        print(f"CI routing failed: {error}", file=sys.stderr)
        sys.exit(1)
