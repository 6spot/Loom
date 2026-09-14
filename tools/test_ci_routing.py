#!/usr/bin/env python3
"""Acceptance cases for path ownership, Git changes and workflow gate wiring."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

from ci_routing import (
    GROUPS, STEPS, SUITES, changed_paths, check_docs, check_notes,
    check_results, classify, emit, validate_plan,
)


ROOT = Path(__file__).resolve().parents[1]


class RoutingTests(unittest.TestCase):
    def assert_route(self, paths, selected=(), skipped=()):
        plan = classify(paths)
        validate_plan(plan)
        for job in selected:
            self.assertTrue(plan["jobs"][job], (paths, job))
        for job in skipped:
            self.assertFalse(plan["jobs"][job], (paths, job))
        return plan

    def test_plain_docs_do_not_build_or_run_product_gates(self):
        for path in ("AGENTS.md", "docs/development/README.md",
                     "apps/chronicle/webapp/README.md", "apps/chronicle/docs/ui.md"):
            with self.subTest(path=path):
                plan = self.assert_route([path], ("documentation", "routing-tests"))
                self.assertEqual(
                    {key for key, value in plan["jobs"].items() if value},
                    {"documentation", "routing-tests"},
                )
                self.assertFalse(any(plan["steps"].values()))

    def test_active_deployment_docs_keep_their_contract_check(self):
        for path in ("README.md", "docs/quickstart.md", "docs/operator-guide.md"):
            self.assertTrue(classify([path])["steps"]["active_docs"])

    def test_studio_does_not_start_backend_or_public_reading_gates(self):
        for path in (
            "apps/chronicle/webapp/src/pages/studio/StudioImportDetailPage.tsx",
            "apps/chronicle/webapp/src/components/studio/ModelSelector.tsx",
            "apps/chronicle/webapp/src/styles/studio.css",
            "apps/chronicle/webapp/src/styles/narrative-review.css",
            "apps/chronicle/webapp/src/styles/person-state-review.css",
            "apps/chronicle/webapp/src/lib/person-state-review-display.ts",
            "apps/chronicle/webapp/src/components/ui/button.tsx",
        ):
            with self.subTest(path=path):
                self.assert_route([path], ("chronicle-static", "web-components", "chronicle"),
                                  ("offline-gate", "chapter-pipeline", "second-round-gate", "third-round-gate"))

    def test_source_reader_selects_reading(self):
        self.assert_route(["apps/chronicle/webapp/src/components/reading/ReadingTimeAxis.tsx"],
                          ("web-components", "second-round-gate"),
                          ("offline-gate", "chapter-pipeline", "third-round-gate"))

    def test_person_state_and_history_have_real_browser_coverage(self):
        for path in (
            "apps/chronicle/webapp/src/components/reading/PersonStateItems.tsx",
            "apps/chronicle/webapp/src/pages/public/EntityPage.tsx",
            "apps/chronicle/webapp/src/pages/public/HistoryPage.tsx",
        ):
            self.assert_route([path], ("web-components", "third-round-gate"),
                              ("offline-gate", "chapter-pipeline"))

    def test_shared_frontend_and_new_files_cover_both_readers(self):
        for path in (
            "apps/chronicle/webapp/src/hooks/useReadingPosition.ts",
            "apps/chronicle/webapp/src/lib/api.ts",
            "apps/chronicle/webapp/src/lib/reading-history.ts",
            "apps/chronicle/webapp/src/lib/reading-types.ts",
            "apps/chronicle/webapp/src/components/reading/ReadingContextPanel.tsx",
            "apps/chronicle/webapp/src/styles/reading-context.css",
            "apps/chronicle/webapp/src/styles/reading-layout.css",
            "apps/chronicle/webapp/src/styles/chronicle.css",
            "apps/chronicle/webapp/package-lock.json",
            "apps/chronicle/webapp/src/new-widget.tsx",
            "apps/chronicle/webapp/tests/fixtures/reading/main.tsx",
        ):
            self.assert_route([path], ("web-components", "second-round-gate", "third-round-gate"))

    def test_rebuilt_assets_follow_the_source_owner(self):
        source = "apps/chronicle/webapp/src/pages/studio/StudioImportsPage.tsx"
        asset = "apps/chronicle/web/dist/assets/index.js"
        plan = self.assert_route([source, asset], ("chronicle-static", "web-components"),
                                 ("second-round-gate", "third-round-gate"))
        self.assertTrue(plan["steps"]["chronicle_web"])
        self.assert_route([asset], ("web-components", "second-round-gate", "third-round-gate"))
        self.assert_route([asset, "apps/chronicle/webapp/README.md"],
                          ("second-round-gate", "third-round-gate"))

    def test_generated_assets_cannot_hide_a_second_source_owner(self):
        self.assert_route([
            "apps/chronicle/webapp/src/pages/studio/StudioImportsPage.tsx",
            "apps/chronicle/webapp/src/components/reading/ReadingTimeAxis.tsx",
            "apps/chronicle/web/dist/assets/index.js",
        ], ("second-round-gate", "web-components"))

    def test_chapter_processing_covers_staged_pg_and_downstream_publishing(self):
        for path in (
            "apps/chronicle/worker/model_provider.py",
            "apps/chronicle/worker/staged_chapter.py",
            "apps/chronicle/read_api/studio_jobs.py",
            "apps/chronicle/persistence/chapter_prompt.py",
        ):
            self.assert_route([path], ("offline-gate", "chapter-pipeline",
                                      "second-round-gate", "third-round-gate"))

    def test_reading_backend_covers_person_state_consumers(self):
        self.assert_route(["apps/chronicle/persistence/narrative_contract.py"],
                          ("reading-contracts", "second-round-gate", "third-round-gate"))

    def test_person_backend_avoids_unrelated_chapter_tests(self):
        self.assert_route(["apps/chronicle/persistence/person_state_projection.py"],
                          ("person-contracts", "third-round-gate"),
                          ("offline-gate", "chapter-pipeline", "second-round-gate"))

    def test_runtime_text_inputs_are_not_documentation(self):
        for path in (
            "apps/chronicle/corpus/first-round/new-source.md",
            "apps/chronicle/worker/config/prompt.md",
            "apps/chronicle/ingestion/fixtures/new-case/README.md",
        ):
            self.assert_route([path], ("chapter-pipeline", "second-round-gate", "third-round-gate"))

    def test_shared_backend_schema_and_dependency_changes_cover_all_contracts(self):
        for path in (
            "apps/chronicle/persistence/migrations/0011_new_state.sql",
            "apps/chronicle/ingestion/schemas/new-contract.json",
            "apps/chronicle/worker/requirements.txt",
            "apps/chronicle/server/src/lib.rs",
            "apps/chronicle/persistence/new-helper.py",
            "compose.chronicle.yaml",
        ):
            self.assert_route([path], GROUPS["chronicle"])

    def test_r2_gate_helpers_also_reach_r3(self):
        for path in ("second_round_gate.py", "reading_scale_fixture.py", "gate_runtime.py"):
            self.assert_route(["apps/chronicle/acceptance/" + path],
                              ("second-round-gate", "third-round-gate"))

    def test_validator_remains_outside_core_rust(self):
        self.assert_route(["apps/loom-validator/src/lib.rs"],
                          ("validator-static",), ("rust", "chronicle"))
        self.assert_route(["apps/loom-validator/Cargo.toml"],
                          ("validator-static", "dependency-policy"), ("rust", "chronicle"))
        self.assert_route(["crates/loom-core/src/lib.rs"], ("rust",),
                          ("validator-static", "chronicle"))
        self.assert_route(["Cargo.lock"], ("rust", "dependency-policy", "validator-static"),
                          ("chronicle",))

    def test_task_notes_select_only_the_owning_metadata_check(self):
        plan = self.assert_route(["docs/tasks/chronicle/third-round/T01-test.md"],
                                 ("documentation", "chronicle-third-round"), ("chronicle", "rust"))
        self.assertEqual(plan["third_round_notes"], ["docs/tasks/chronicle/third-round/T01-test.md"])
        self.assert_route(["docs/tasks/ci-governance/t06-routing.md"], ("ledger",), ("chronicle", "rust"))
        self.assert_route(["docs/tasks/validator-recert/T01.md"], ("validator-ledger",),
                          ("ledger", "rust", "chronicle"))

    def test_ci_policy_changes_and_unknown_root_code_are_conservative(self):
        for path in ("tools/ci_routing.py", ".github/workflows/ci.yml", "new-tool.py"):
            self.assertTrue(all(classify([path])["jobs"].values()), path)
        self.assert_route([".github/workflows/chronicle.yml"], GROUPS["chronicle"], ("rust", "validator-static"))
        self.assert_route([".github/workflows/validator.yml"], GROUPS["validator"], ("rust", "chronicle"))

    def test_dispatch_is_full_and_empty_changes_still_test_routing(self):
        full = classify([], full=True)
        self.assertTrue(all(full["jobs"].values()))
        self.assertTrue(all(full["steps"].values()))
        self.assertTrue(all(full["suites"].values()))
        self.assertEqual([job for job, on in classify([])["jobs"].items() if on], ["routing-tests"])

    def test_selection_is_monotone_for_mixed_owners(self):
        paths = ["apps/chronicle/webapp/src/styles/studio.css",
                 "apps/chronicle/persistence/person_state_store.py", "crates/loom-core/src/lib.rs"]
        mixed = classify(paths)
        for path in paths:
            for job, selected in classify([path])["jobs"].items():
                if selected:
                    self.assertTrue(mixed["jobs"][job], (path, job))

    def test_plan_schema_rejects_missing_flags_and_non_booleans(self):
        for mutate in (
            lambda p: p["jobs"].pop("second-round-gate"),
            lambda p: p["jobs"].update({"rust": "false"}),
            lambda p: p.update({"version": 2}),
            lambda p: p["jobs"].update({"chronicle": True}),
        ):
            plan = classify([])
            mutate(plan)
            with self.assertRaises(ValueError):
                validate_plan(plan)


class GateTests(unittest.TestCase):
    def results(self, plan, group):
        return {"changes": {"result": "success"}, **{
            job: {"result": "success" if plan["jobs"][job] else "skipped"}
            for job in GROUPS[group]
        }}

    def test_expected_skips_and_successes_are_accepted(self):
        plan = classify(["apps/chronicle/webapp/src/styles/studio.css"])
        for group in GROUPS:
            self.assertEqual(check_results(plan, self.results(plan, group), group), [])

    def test_selected_skip_failure_cancellation_and_missing_results_block(self):
        plan = classify(["apps/chronicle/worker/model_provider.py"])
        for result in ("skipped", "failure", "cancelled", None):
            with self.subTest(result=result):
                needs = self.results(plan, "chronicle")
                needs["chapter-pipeline"] = {"result": result}
                self.assertTrue(check_results(plan, needs, "chronicle"))
        needs = self.results(plan, "chronicle")
        del needs["chapter-pipeline"]
        self.assertTrue(check_results(plan, needs, "chronicle"))

    def test_classifier_cannot_be_skipped_or_failed(self):
        plan = classify([])
        for state in ("skipped", "failure", "cancelled", None):
            needs = self.results(plan, "repository")
            needs["changes"] = {"result": state}
            self.assertTrue(check_results(plan, needs, "repository"))

    def test_chronicle_failure_reaches_the_repository_gate(self):
        plan = classify(["apps/chronicle/webapp/src/styles/studio.css"])
        needs = self.results(plan, "repository")
        needs["chronicle"]["result"] = "failure"
        self.assertTrue(check_results(plan, needs, "repository"))

    def test_unselected_failure_is_not_hidden(self):
        plan = classify([])
        needs = self.results(plan, "repository")
        needs["rust"]["result"] = "failure"
        self.assertTrue(check_results(plan, needs, "repository"))


class GitInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        previous = os.getcwd()
        os.chdir(self.temp.name)
        self.addCleanup(os.chdir, previous)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "CI Routing Test")
        self.git("config", "user.email", "ci-routing@example.invalid")
        self.write("README.md", "base\n")
        self.base = self.commit()

    def git(self, *args):
        return subprocess.check_output(["git", *args], text=True).strip()

    def write(self, name, content="test\n"):
        path = Path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def test_pr_uses_merge_base_not_unrelated_new_base_changes(self):
        self.git("checkout", "-qb", "feature")
        self.write("docs/feature.md")
        head = self.commit()
        self.git("checkout", "-q", "main")
        self.write("crates/base-only.rs")
        base = self.commit()
        event = {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}
        self.assertEqual(changed_paths("pull_request", event), ["docs/feature.md"])

    def test_rename_delete_and_unusual_names_are_preserved(self):
        old = "apps/chronicle/webapp/src/pages/studio/StudioOld.tsx"
        new = "apps/chronicle/webapp/src/components/reading/ReadingNew.tsx"
        self.write(old)
        before = self.commit()
        Path(new).parent.mkdir(parents=True, exist_ok=True)
        self.git("mv", old, new)
        self.git("rm", "-q", "README.md")
        unusual = "docs/a space\nand newline.md"
        self.write(unusual)
        after = self.commit()
        paths = changed_paths("push", {"before": before, "after": after})
        self.assertEqual(set(paths), {old, new, "README.md", unusual})
        plan = classify(paths)
        self.assertTrue(plan["suites"]["studio"])
        self.assertTrue(plan["jobs"]["second-round-gate"])

    def test_initial_push_uses_empty_tree(self):
        self.assertEqual(changed_paths("push", {"before": "0" * 40, "after": self.base}), ["README.md"])

    def test_unknown_events_fail_instead_of_selecting_nothing(self):
        with self.assertRaises(ValueError):
            changed_paths("unexpected", {})

    def test_github_output_is_one_json_line_even_for_unusual_names(self):
        plan = classify(["docs/a space\nand newline.md"])
        with patch("builtins.print"):
            emit(plan, "output.txt", "summary.md")
        lines = Path("output.txt").read_text().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0].split("=", 1)[1]), plan)

    def test_deleted_docs_and_notes_do_not_read_missing_files(self):
        plan = classify(["docs/gone.md", "docs/tasks/chronicle/third-round/T01-gone.md"])
        check_docs(plan)
        check_notes(plan, "third")

    def test_doc_check_rejects_missing_links_but_not_fenced_examples(self):
        self.write("docs/target.md")
        fence = chr(96) * 3
        self.write("docs/guide.md", "[target](target.md)\n" + fence +
                   "\n[example](missing.md)\n" + fence + "\n")
        plan = classify(["docs/guide.md"])
        with patch("builtins.print"):
            check_docs(plan)
        self.write("docs/guide.md", "[broken](missing.md)\n")
        with self.assertRaises(ValueError):
            check_docs(plan)

    def test_note_front_matter_is_still_enforced(self):
        name = "docs/tasks/chronicle/third-round/T01-case.md"
        self.write(name, "---\ntask: C2-R3-T01\nissue: 123\nkind: implementation\n---\n")
        plan = classify([name])
        with patch("builtins.print"):
            check_notes(plan, "third")
        self.write(name, "---\ntask: C2-R3-T02\nissue: 123\nkind: implementation\n---\n")
        with self.assertRaises(ValueError):
            check_notes(plan, "third")


class WorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflows = {
            name: yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)
            for name in ("ci.yml", "chronicle.yml", "validator.yml")
        }

    def test_shared_classifier_is_the_only_route_definition(self):
        for name, workflow in self.workflows.items():
            text = (ROOT / ".github/workflows" / name).read_text()
            self.assertIn("python3 tools/ci_routing.py classify", text)
            self.assertNotIn("git diff --name-only", text)
            self.assertNotIn("case \"$path\"", text)
            if name != "chronicle.yml":
                self.assertIn("pull_request", workflow["on"])
                self.assertNotIn("paths", workflow["on"]["push"])
                self.assertNotIn("paths", workflow["on"]["pull_request"])

    def test_all_gates_depend_on_exactly_the_jobs_they_validate(self):
        for filename, group, gate in (
            ("ci.yml", "repository", "repository-gate"),
            ("chronicle.yml", "chronicle", "chronicle-gate"),
            ("validator.yml", "validator", "validator-gate"),
        ):
            jobs = self.workflows[filename]["jobs"]
            self.assertEqual(set(jobs[gate]["needs"]), {"changes", *GROUPS[group]})
            self.assertEqual(jobs[gate]["if"], "always()")
            self.assertIn("--group " + group, str(jobs[gate]["steps"]))
            for job in GROUPS[group]:
                self.assertIn(job, jobs)
                condition = jobs[job].get("if", "")
                if job == "routing-tests":
                    self.assertEqual(condition, "always()")
                else:
                    prefix = "fromJSON(needs.changes.outputs.plan).jobs"
                    self.assertIn(condition, {prefix + "['" + job + "']", prefix + "." + job})

    def test_chronicle_is_called_once_and_remains_manually_runnable(self):
        root = self.workflows["ci.yml"]
        callee = self.workflows["chronicle.yml"]
        self.assertEqual(root["jobs"]["chronicle"]["uses"], "./.github/workflows/chronicle.yml")
        self.assertEqual(root["jobs"]["chronicle"]["with"]["plan"], "$" + "{{ needs.changes.outputs.plan }}")
        self.assertIn("workflow_call", callee["on"])
        self.assertIn("workflow_dispatch", callee["on"])
        self.assertNotIn("pull_request", callee["on"])
        self.assertNotIn("push", callee["on"])

    def test_existing_browser_and_database_contracts_remain_executable(self):
        jobs = self.workflows["chronicle.yml"]["jobs"]
        for job, script in (
            ("offline-gate", "first_round_gate.py"),
            ("second-round-gate", "second_round_gate.py"),
            ("third-round-gate", "third_round_gate.py"),
        ):
            steps = str(jobs[job]["steps"])
            self.assertIn(script, steps)
            self.assertIn("--mode fixture", steps)
            if job != "offline-gate":
                self.assertIn("--browser-required", steps)
                self.assertIn("performance_budget", steps)
        self.assertIn("test_staged_chapter_pipeline_postgres.py", str(jobs["chapter-pipeline"]))
        self.assertIn("test_studio_jobs_postgres.py", str(jobs["chapter-pipeline"]))
        self.assertIn("-k publish_faults", str(jobs["reading-contracts"]))
        self.assertIn("test_person_state_pipeline_postgres.py", str(jobs["person-contracts"]))
        self.assertNotIn("services", jobs["web-components"])
        self.assertNotIn("docker build", str(jobs["web-components"]))
        self.assertEqual(str(jobs).count("npm --prefix apps/chronicle/webapp test"), 1)

    def test_step_and_suite_flags_have_consumers(self):
        text = "\n".join((ROOT / ".github/workflows" / name).read_text() for name in self.workflows)
        for step in STEPS:
            self.assertIn(".steps." + step, text)
        for suite in SUITES:
            self.assertIn(".suites." + suite, text)

    def test_ci_scripts_have_code_owner_coverage(self):
        owners = (ROOT / ".github/CODEOWNERS").read_text()
        for name in ("ci_routing.py", "test_ci_routing.py", "requirements-ci.txt"):
            self.assertIn("/tools/" + name + " @6spot", owners)


if __name__ == "__main__":
    unittest.main()
