import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qa import companies_contact_qualification as qualification

ROOT = Path(__file__).resolve().parents[1]


def result(output=""):
    return subprocess.CompletedProcess(["synthetic"], 0, output, "")


def junit(*, skipped="0", names=None, child=""):
    names = qualification.TEST_NAMES if names is None else names
    cases = "".join(
        f'<testcase classname="tests.service_integration.test_returning_reuse_postgresql" '
        f'name="{name}">{child}</testcase>' for name in names
    )
    return f'<testsuites><testsuite tests="2" failures="0" errors="0" skipped="{skipped}">{cases}</testsuite></testsuites>'


class ContactQualificationTests(unittest.TestCase):
    def test_minimal_dependencies_are_only_five_hash_locked_test_packages(self):
        original = (ROOT / "backend/requirements-dev.lock").read_text()
        selected, entries = qualification.minimal_requirements(original)
        self.assertEqual(set(entries), qualification.PACKAGES)
        self.assertNotIn("packaging==", selected)
        self.assertNotIn("typing-extensions==", selected)
        self.assertNotIn("+", selected)
        selected_again, same = qualification.minimal_requirements(selected)
        self.assertEqual(same, entries)
        self.assertEqual(selected_again, selected)
        for name, (version, hashes) in entries.items():
            self.assertIn(f"{name}=={version}", selected)
            self.assertTrue(hashes)
            for digest in hashes:
                self.assertIn(digest, original)

    def test_missing_or_duplicate_lock_entry_is_rejected(self):
        original = (ROOT / "backend/requirements-dev.lock").read_text()
        selected, _ = qualification.minimal_requirements(original)
        for value in ("", selected.replace("pytest==", "not-pytest=="), selected + selected):
            with self.subTest(value=value[:30]), self.assertRaises(qualification.QualificationError):
                qualification.minimal_requirements(value)

    def test_exact_wheel_content_must_match_the_reviewed_hash(self):
        wheel = b"synthetic wheel bytes"
        digest = hashlib.sha256(wheel).hexdigest()
        metadata = json.dumps({"urls": [{"filename": "pytest-9.0.3-py3-none-any.whl",
                                        "digests": {"sha256": digest},
                                        "url": "https://files.pythonhosted.org/test.whl"}]}).encode()
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "wheels"
            with patch.object(qualification, "_download", side_effect=[metadata, wheel]) as download:
                proof = qualification.prepare_wheelhouse({"pytest": ("9.0.3", {digest})}, target)
            self.assertEqual(proof, {"pytest-9.0.3-py3-none-any.whl": digest})
            self.assertEqual(download.call_count, 2)
            with (patch.object(qualification, "_download", side_effect=[metadata, b"changed"]),
                  self.assertRaisesRegex(qualification.QualificationError, "SHA-256")):
                qualification.prepare_wheelhouse({"pytest": ("9.0.3", {digest})}, Path(temporary) / "bad")

    def test_metadata_cannot_add_a_wheel_not_in_lock(self):
        value = json.dumps({"urls": [{"filename": "pytest-9.0.3-py3-none-any.whl",
                                     "digests": {"sha256": "a" * 64}}]}).encode()
        with tempfile.TemporaryDirectory() as temporary, patch.object(qualification, "_download", return_value=value) as download:
            with self.assertRaises(qualification.QualificationError):
                qualification.prepare_wheelhouse({"pytest": ("9.0.3", {"b" * 64})}, Path(temporary) / "wheels")
            self.assertEqual(download.call_count, 1)

    def test_download_rejects_credential_and_nonpackage_locations(self):
        for url in ("http://files.pythonhosted.org/a", "https://files.pythonhosted.org.evil/a",
                    "https://user:password@files.pythonhosted.org/a", "file:///secret"):
            with self.subTest(url=url), patch.object(qualification.urllib.request, "urlopen") as request:
                with self.assertRaises(qualification.QualificationError):
                    qualification._download(url, maximum=100, host="files.pythonhosted.org")
                request.assert_not_called()

    def test_receipt_requires_two_exact_tests_and_never_accepts_skips(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "result.xml"
            path.write_text(junit())
            proof = qualification.validate_junit(path)
            self.assertEqual(proof["contact_concurrency_tests"], 2)
            self.assertTrue(proof["contact_concurrency_verified"])
            for document in (junit(skipped="1"), junit(names={"different", "tests"}),
                             junit(child="<failure/>"), junit().replace('tests="2"', 'tests="3"'),
                             junit().replace("tests.service_integration", "unrelated"), "<invalid"):
                path.write_text(document)
                with self.subTest(document=document[:60]), self.assertRaises(qualification.QualificationError):
                    qualification.validate_junit(path)

    def test_git_archive_uses_exact_commit_and_rejects_app_mount_or_alias(self):
        for name, link in (("backend/app/override.py", False), ("backend/tests/alias.py", True),
                           ("backend/tests/../../escape", False)):
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode="w") as archive:
                entry = tarfile.TarInfo(name)
                if link:
                    entry.type, entry.linkname = tarfile.SYMTYPE, "/etc/passwd"
                archive.addfile(entry)
            with tempfile.TemporaryDirectory() as temporary, patch.object(
                qualification.subprocess, "run", return_value=result(stream.getvalue()),
            ) as command:
                with self.assertRaises(qualification.QualificationError):
                    qualification.extract_test_sources(ROOT, "a" * 40, Path(temporary) / "source")
                arguments = command.call_args.args[0]
                self.assertIn("a" * 40, arguments)
                self.assertNotIn("backend/app", arguments)

    def test_helper_containers_use_only_isolated_network_and_test_overlays(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            environment = directory / "postgres.env"
            environment.write_text("POSTGRES_USER=qualification\nPOSTGRES_PASSWORD=synthetic\nLD_LIBRARY_PATH=/must-not-pass\n")

            def sources(_root, _commit, target):
                source = target / "backend"
                (source / "tests").mkdir(parents=True)
                (source / "requirements-dev.lock").write_text((ROOT / "backend/requirements-dev.lock").read_text())
                return "b" * 64

            inspected = json.dumps([{"Config": {"Labels": {qualification.OWNER_LABEL: "test-owner"},
                                                 "Env": ["PYTHONPATH=/opt/mcp-deps:/app"]}}])
            diagnostic = directory / "fast-contact-check.private.log"
            with (
                patch.object(qualification.os, "name", "posix"),
                patch.object(qualification.os, "getuid", return_value=1001, create=True),
                patch.object(qualification.os, "getgid", return_value=1001, create=True),
                patch.object(qualification, "inspect_image", return_value="sha256:" + "a" * 64),
                patch.object(qualification, "extract_test_sources", side_effect=sources),
                patch.object(qualification, "prepare_wheelhouse", return_value={}),
                patch.object(qualification, "validate_diagnostic_path") as validate_path,
                patch.object(qualification, "capture", return_value="") as capture,
                patch.object(qualification, "validate_junit", return_value={"contact_concurrency_tests": 2}),
                patch.object(qualification, "run", return_value=result(inspected)) as command,
            ):
                qualification.run_contact_tests(image="candidate", server_id="a" * 64, owner="test-owner",
                    tempdir=directory, env_file=environment, container_name="test-contact",
                    dependency_container_name="test-dependencies", source_root=ROOT, source_commit="a" * 40,
                    diagnostic_path=diagnostic)
            validate_path.assert_called_once_with(diagnostic)
            capture.assert_called_once_with(["docker", "start", "--attach", "test-contact"],
                                            timeout=180, diagnostic_path=diagnostic)
            commands = [call.args[0] for call in command.call_args_list]
            containers = [args for args in commands if args[:2] == ["docker", "create"]]
            self.assertEqual(len(containers), 2)
            prep, tests = containers
            self.assertEqual(prep[prep.index("--network") + 1], "none")
            self.assertIn("--no-index", prep)
            self.assertIn("--no-deps", prep)
            self.assertIn("--require-hashes", prep)
            self.assertNotIn("--env-file", prep)
            self.assertEqual(tests[tests.index("--network") + 1], "container:" + "a" * 64)
            self.assertIn(qualification.TEST_FILE, tests)
            self.assertIn("PYTEST_DISABLE_PLUGIN_AUTOLOAD=1", tests)
            self.assertIn("PYTHONPATH=/qa-overlay:/opt/mcp-deps:/app", tests)
            self.assertNotIn("LD_LIBRARY_PATH", (directory / "contact.env").read_text())
            for args in containers:
                self.assertNotIn("--privileged", args)
                self.assertNotIn("--publish", args)
                self.assertIn("512m", args)
                self.assertIn("max-size=1m", args)
                self.assertIn("max-file=2", args)
                self.assertFalse(any("target=/app/app" in item or "target=/opt/venv" in item for item in args))

    def test_unrelated_database_server_is_rejected_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with (
                patch.object(qualification.os, "name", "posix"),
                patch.object(qualification, "inspect_image", return_value="sha256:" + "a" * 64),
                patch.object(qualification, "run", return_value=result(json.dumps([{"Config": {"Labels": {}}}]))) as command,
                self.assertRaisesRegex(qualification.QualificationError, "unrelated"),
            ):
                qualification.run_contact_tests(image="candidate", server_id="a" * 64, owner="owner",
                    tempdir=directory, env_file=directory / "postgres.env", container_name="test",
                    dependency_container_name="deps", source_root=ROOT, source_commit="a" * 40)
            self.assertEqual(command.call_count, 2)

    def test_diagnostic_path_requires_new_fixed_log_in_private_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            directory.chmod(0o700)
            path = directory / "fast-contact-check.private.log"
            qualification.validate_diagnostic_path(None)
            qualification.validate_diagnostic_path(path)
            with self.assertRaises(qualification.QualificationError):
                qualification.validate_diagnostic_path(directory / "public.log")
            path.write_text("existing diagnostic must survive")
            with self.assertRaises(qualification.QualificationError):
                qualification.validate_diagnostic_path(path)
            self.assertEqual(path.read_text(), "existing diagnostic must survive")


if __name__ == "__main__":
    unittest.main()
