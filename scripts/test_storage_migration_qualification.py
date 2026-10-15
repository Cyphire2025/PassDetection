"""Disposable storage capacity stays sufficient without retrying copy failures."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

QA = Path(__file__).resolve().parent / "qa"
SPEC = importlib.util.spec_from_file_location(
    "storage_migration_qualification_tests_target", QA / "run_storage_migration_qualification.py"
)
assert SPEC is not None and SPEC.loader is not None
qualification = importlib.util.module_from_spec(SPEC)
with patch.object(sys, "path", [str(QA), *sys.path]):
    SPEC.loader.exec_module(qualification)


class StorageMigrationQualificationTests(unittest.TestCase):
    def run_fixture(self, output, *, copy_fails=False):
        commands = []
        copy_attempts = []

        def run(*arguments, **options):
            commands.append(arguments)
            if arguments[:4] == ("docker", "inspect", "--format", "{{.State.Health.Status}}"):
                return "healthy"
            if arguments[:4] == ("docker", "inspect", "--format", "{{.State.ExitCode}}"):
                return "0"
            return ""

        def process(arguments, **options):
            if arguments[:3] == ["docker", "start", "--attach"]:
                copy_attempts.append(arguments)
                if copy_fails:
                    raise subprocess.CalledProcessError(1, arguments)
                (output / "migration-evidence.json").write_text(
                    json.dumps({"qualification_complete": True}), encoding="utf-8"
                )
            return SimpleNamespace(stdout="", stderr="", returncode=0)

        with (
            patch.object(qualification, "OUTPUT", output),
            patch.object(qualification, "run", side_effect=run),
            patch.object(qualification, "write_qualification_identity"),
            patch.object(qualification.subprocess, "run", side_effect=process),
            patch("builtins.print"),
        ):
            if copy_fails:
                with self.assertRaises(subprocess.CalledProcessError):
                    qualification.main()
            else:
                qualification.main()
        return commands, copy_attempts

    def test_both_disposable_providers_fit_all_fixture_collections_on_small_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            commands, _ = self.run_fixture(Path(directory))
        providers = [command for command in commands if qualification.STORAGE_IMAGE in command]
        self.assertEqual(len(providers), 2)
        # The real failed run exhausted 69 automatically sized GiB slots.
        # Eleven occupied fixture buckets need seven slots each; even a runner
        # with only 2 GiB free must have room for all 77 slots before pagination.
        required_slots = 11 * 7
        self.assertLess(69, required_slots)
        for command in providers:
            with self.subTest(provider=command[command.index("--name") + 1]):
                self.assertIn("-volume.max=0", command)
                size = int(next(value.split("=", 1)[1] for value in command
                                if value.startswith("-master.volumeSizeLimitMB=")))
                self.assertGreater(size, 0)
                self.assertGreaterEqual(2048 // size, required_slots)
                self.assertFalse(any(value.startswith(("-volume.minFreeSpace", "-master.volumePreallocate"))
                                     for value in command))
                self.assertIn("-s3.allowDeleteBucketNotEmpty=false", command)
                self.assertIn("-s3.autoCreateBucket=false", command)

    def test_copy_failure_propagates_once_and_cleans_only_created_fixture_containers(self):
        with tempfile.TemporaryDirectory() as directory:
            commands, attempts = self.run_fixture(Path(directory), copy_fails=True)
        self.assertEqual(len(attempts), 1)
        removed = [command for command in commands if command[:2] == ("docker", "rm")]
        self.assertEqual(removed, [
            ("docker", "rm", "--force", "--volumes", f"{qualification.PREFIX}-{role}")
            for role in ("copy", "target", "source")
        ])
        self.assertEqual(commands[-1], ("docker", "network", "rm", qualification.PREFIX))
