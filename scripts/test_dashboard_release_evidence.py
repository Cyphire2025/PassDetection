"""Manual runtime evidence must follow reviewed pins and preserve isolation gates."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from qa.dashboard_release_evidence import (
    reviewed_runtime_versions,
    validate_runtime_facts,
)


class DashboardReleaseEvidenceTests(unittest.TestCase):
    def test_versions_follow_the_installed_package_locks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "backend").mkdir()
            (root / "frontend").mkdir()
            (root / "backend/requirements.lock").write_text("pypdf==6.19.0 \\\n    --hash=sha256:synthetic\n", encoding="utf-8")
            (root / "frontend/package-lock.json").write_text(json.dumps({"packages": {
                "node_modules/next": {"version": "16.3.6"},
                "node_modules/sharp": {"version": "0.35.5"},
            }}), encoding="utf-8")
            self.assertEqual(reviewed_runtime_versions(root), {
                "backend": {"pypdf": "6.19.0"}, "frontend": {"next": "16.3.6", "sharp": "0.35.5"},
            })
            for lock in ("pypdf>=6.19.0\n", "pypdf==6.19.0\npypdf==6.16.1\n"):
                (root / "backend/requirements.lock").write_text(lock, encoding="utf-8")
                with self.subTest(lock=lock), self.assertRaises(ValueError):
                    reviewed_runtime_versions(root)

    def test_current_runtime_pins_pass_and_prior_packages_are_rejected(self):
        expected = reviewed_runtime_versions(Path(__file__).resolve().parents[1])
        for service, versions in expected.items():
            libheif = "1.23.2" if service == "backend" else "1.23.5"
            facts = {**versions, "libheif": libheif, "uid": 1001,
                     "forbidden_artifacts": [], "build_tools": []}
            validate_runtime_facts(service, facts, versions)
            for package in versions:
                stale = {**facts, package: "stale-runtime-version"}
                with self.subTest(service=service, package=package), self.assertRaises(ValueError):
                    validate_runtime_facts(service, stale, versions)

    def test_frontend_rejects_the_prior_libheif_even_with_current_package_pins(self):
        versions = reviewed_runtime_versions(Path(__file__).resolve().parents[1])["frontend"]
        facts = {**versions, "libheif": "1.23.2", "uid": 1001,
                 "forbidden_artifacts": [], "build_tools": []}
        with self.assertRaisesRegex(ValueError, "frontend libheif"):
            validate_runtime_facts("frontend", facts, versions)

    def test_native_nonroot_artifact_and_build_tool_gates_remain_mandatory(self):
        good = {"pypdf": "6.19.0", "libheif": "1.23.2", "uid": 1001,
                "forbidden_artifacts": [], "build_tools": []}
        for mutation in ({"libheif": "1.23.1"}, {"uid": 0},
                         {"forbidden_artifacts": ["/app/tooling/npm-security"]},
                         {"forbidden_artifacts": ["/app/.env"]}, {"build_tools": ["setuptools"]}):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_runtime_facts("backend", {**good, **mutation}, {"pypdf": "6.19.0"})
        missing = copy.copy(good)
        del missing["build_tools"]
        with self.assertRaises(ValueError):
            validate_runtime_facts("backend", missing, {"pypdf": "6.19.0"})
