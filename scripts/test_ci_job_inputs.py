"""Fail-closed dependency and exact-Git-tree contracts for incremental CI."""
from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from ci_job_inputs import (
    ALL_JOBS,
    BACKEND_FRONTEND_INPUTS,
    FRONTEND_BACKEND_INPUTS,
    JOBS,
    REUSABLE_JOBS,
    classify_paths,
    fingerprint_job,
    fingerprints,
    read_git_tree,
)


def entry(content: str, mode: str = "100644") -> tuple[str, str, str]:
    return mode, "blob", hashlib.sha1(content.encode(), usedforsecurity=False).hexdigest()


def tree() -> dict[str, tuple[str, str, str]]:
    return {
        ".github/workflows/ci.yml": entry("workflow"),
        "scripts/ci_job_inputs.py": entry("input policy"),
        "backend/app/main.py": entry("backend"),
        "frontend/app/page.tsx": entry("frontend"),
        "mcp-connector/src/main.py": entry("connector"),
    }


class InputPolicyTests(unittest.TestCase):
    def test_only_pure_routine_jobs_can_be_reused(self):
        self.assertEqual(REUSABLE_JOBS, {
            "backend-test", "backend-service-integration", "backend-migration-rehearsal",
            "frontend-browser", "connector-windows",
        })
        self.assertLess(REUSABLE_JOBS, ALL_JOBS)

    def test_backend_change_invalidates_real_backend_connector_but_not_mock_browser(self):
        selected = classify_paths(["backend/app/application/staff.py"])
        self.assertIn("backend-test", selected)
        self.assertIn("backend-service-integration", selected)
        self.assertIn("backend-migration-rehearsal", selected)
        self.assertIn("backend-dependency-audit", selected)
        self.assertIn("connector-windows", selected)
        self.assertIn("docker-build", selected)
        self.assertNotIn("frontend-browser", selected)

    def test_frontend_change_keeps_unrelated_backend_fingerprints(self):
        before = tree()
        after = {**before, "frontend/app/page.tsx": entry("fixed UI")}
        for job in REUSABLE_JOBS - {"frontend-browser"}:
            self.assertEqual(fingerprint_job(job, before), fingerprint_job(job, after))
        for job in ("frontend-browser", "frontend-lint", "docker-build"):
            self.assertNotEqual(fingerprint_job(job, before), fingerprint_job(job, after))

    def test_backend_tests_are_not_image_inputs_but_invalidate_both_test_lanes(self):
        self.assertEqual(classify_paths(["backend/tests/conftest.py"]), {
            "backend-static-checks", "backend-test", "backend-service-integration",
        })

    def test_frontend_tests_stay_in_build_context(self):
        self.assertIn("docker-build", classify_paths(["frontend/features/a.test.tsx"]))

    def test_connector_has_its_own_lane_without_unrelated_image_build(self):
        self.assertEqual(classify_paths(["mcp-connector/src/gc_mcp_connector/cli.py"]), {
            "backend-static-checks", "connector-windows",
        })

    def test_existing_cross_component_source_contracts_are_not_skipped(self):
        for path in BACKEND_FRONTEND_INPUTS:
            self.assertIn("backend-test", classify_paths([path]))
        for path in FRONTEND_BACKEND_INPUTS:
            self.assertIn("frontend-lint", classify_paths([path]))
        self.assertIn("backend-test", classify_paths(["mobile/contracts/mobile-api.openapi.json"]))
        self.assertIn("frontend-browser", classify_paths(["backend/contracts/api.openapi.json"]))

    def test_readme_docs_and_policy_test_edits_avoid_unrelated_images(self):
        for path in ("README.md", "docs/deployment-modes.md", "scripts/test_release_manifest.py",
                     "scripts/qa/test_workload_capacity.py"):
            self.assertEqual(classify_paths([path]), {"backend-static-checks"})
        self.assertEqual(classify_paths(["docs/sources/enterprise-dashboard-ui-transformation-prompt.md"]),
                         {"backend-static-checks", "frontend-lint"})

    def test_executable_docs_and_machine_readable_policy_are_not_exempt(self):
        for path in ("docs/example.py", "docs/engineering-claims.json", "docs/remediation/evidence.json"):
            self.assertEqual(classify_paths([path]), ALL_JOBS)

    def test_shared_and_unknown_changes_invalidate_every_fingerprint(self):
        for path in ("scripts/ci_planner.py", "scripts/qa/check.py", ".github/workflows/ci.yml",
                     "tooling/toolchain.json", "nginx/conf.d/default.conf", ".gitattributes",
                     "docker-compose.prod.yml", "new-component/source.py"):
            before = tree()
            after = {**before, path: entry("changed")}
            self.assertEqual(classify_paths([path]), ALL_JOBS)
            self.assertTrue(all(fingerprint_job(job, before) != fingerprint_job(job, after) for job in JOBS))

    def test_addition_deletion_rename_and_executable_mode_change_invalidate(self):
        base = tree()
        with_file = {**base, "backend/app/a.py": entry("identical bytes")}
        renamed = {**base, "backend/app/b.py": entry("identical bytes")}
        executable = {**base, "backend/app/a.py": entry("identical bytes", "100755")}
        values = {fingerprint_job("backend-test", value) for value in (base, with_file, renamed, executable)}
        self.assertEqual(len(values), 4)

    def test_order_independence_and_job_domain_separation(self):
        data = tree()
        self.assertEqual(fingerprints(data), fingerprints(dict(reversed(list(data.items())))))
        self.assertEqual(len(set(fingerprints(data).values())), len(JOBS))

    def test_cumulative_selection_does_not_forget_earlier_backend_change(self):
        selected = classify_paths(["backend/app/main.py", "frontend/app/page.tsx"])
        self.assertIn("backend-test", selected)
        self.assertIn("frontend-browser", selected)

    def test_invalid_paths_and_objects_refuse_reuse(self):
        for path in ("", "/absolute", "../escape", "a/../b", "a//b", "a\\b", "a\nb"):
            with self.assertRaises(ValueError):
                classify_paths([path])
        for bad in (("120000", "blob", "a" * 40), ("160000", "commit", "a" * 40),
                    ("100644", "blob", "HEAD")):
            with self.assertRaises(ValueError):
                fingerprint_job("backend-test", {**tree(), "unreviewed": bad})
        with self.assertRaises(ValueError):
            fingerprint_job("unknown", tree())
        with self.assertRaises(ValueError):
            fingerprints({})


class CommittedTreeTests(unittest.TestCase):
    def test_local_edits_untracked_files_and_dirty_workspace_cannot_forge_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*arguments: str) -> str:
                return subprocess.check_output(["git", "-C", str(root), *arguments], text=True).strip()

            git("init", "--quiet")
            git("config", "user.email", "synthetic-ci@example.invalid")
            git("config", "user.name", "Synthetic CI")
            workflow = root / ".github/workflows/ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text("name: fixture\n", encoding="utf-8")
            git("add", ".")
            git("commit", "--quiet", "-m", "synthetic fixture")
            revision = git("rev-parse", "HEAD")
            actual = read_git_tree(root, revision)
            workflow.write_text("name: changed locally\n", encoding="utf-8")
            (root / "untracked.py").write_text("never trusted\n", encoding="utf-8")
            self.assertEqual(actual, read_git_tree(root, revision))
            self.assertEqual(set(actual), {".github/workflows/ci.yml"})
            with self.assertRaises(ValueError):
                read_git_tree(root, git("rev-parse", "HEAD^{tree}"))
            for mutable in ("HEAD", "main", "a" * 39, "--help"):
                with self.assertRaises(ValueError):
                    read_git_tree(root, mutable)


if __name__ == "__main__":
    unittest.main()
