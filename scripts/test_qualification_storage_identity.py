"""QA identity permissions preserve private files and retryable setup."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qa.qualification_storage_identity import (
    OWNERSHIP_SCRIPT,
    write_qualification_identity,
)

IMAGE = "chrislusf/seaweedfs:4.47@sha256:" + "a" * 64


class QualificationIdentityTests(unittest.TestCase):
    def test_linux_changes_only_the_staged_file_using_the_provider_account(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"

            def helper(command, **options):
                mount = command[command.index("--mount") + 1]
                source = Path(mount.removeprefix("type=bind,source=").removesuffix(",target=/identity.json"))
                self.assertEqual(source.parent, path.parent)
                self.assertEqual(source.read_text(), "synthetic-one")
                self.assertEqual(command[command.index("--user") + 1], "0:0")
                self.assertEqual(command[command.index("--network") + 1], "none")
                self.assertEqual(command[-3:], [IMAGE, "-ec", OWNERSHIP_SCRIPT])
                self.assertTrue(options["check"])
                self.assertEqual(options["timeout"], 120)
                self.assertNotIn("synthetic-one", " ".join(command))

            with patch("qa.qualification_storage_identity.sys.platform", "linux"), patch(
                "qa.qualification_storage_identity.subprocess.run", side_effect=helper
            ) as operation:
                write_qualification_identity(path, "synthetic-one", IMAGE)
            operation.assert_called_once()
            self.assertEqual(path.read_text(), "synthetic-one")
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_repeated_setup_replaces_without_reading_the_previous_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            with patch("qa.qualification_storage_identity.sys.platform", "linux"), patch(
                "qa.qualification_storage_identity.subprocess.run"
            ) as operation:
                write_qualification_identity(path, "first", IMAGE)
                with patch.object(Path, "read_text", side_effect=PermissionError("provider-owned")):
                    write_qualification_identity(path, "second", IMAGE)
            self.assertEqual(operation.call_count, 2)
            self.assertEqual(path.read_text(), "second")

    def test_permission_helper_failure_preserves_existing_bytes_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            path.write_text("previous")
            with patch("qa.qualification_storage_identity.sys.platform", "linux"), patch(
                "qa.qualification_storage_identity.subprocess.run", side_effect=subprocess.CalledProcessError(1, "docker")
            ), self.assertRaises(subprocess.CalledProcessError):
                write_qualification_identity(path, "replacement", IMAGE)
            self.assertEqual(path.read_text(), "previous")
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_mutable_or_other_provider_image_is_rejected(self):
        for image in ("chrislusf/seaweedfs:latest", "other/image@sha256:" + "a" * 64):
            with self.subTest(image=image), self.assertRaises(ValueError):
                write_qualification_identity(Path("unused.json"), "synthetic", image)

    def test_symlink_destination_is_rejected_before_writing(self):
        with patch.object(Path, "is_symlink", return_value=True), self.assertRaises(ValueError):
            write_qualification_identity(Path("unused.json"), "synthetic", IMAGE)

    def test_windows_docker_bind_keeps_atomic_write_without_unix_chown(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            with patch("qa.qualification_storage_identity.sys.platform", "win32"), patch(
                "qa.qualification_storage_identity.subprocess.run"
            ) as operation:
                write_qualification_identity(path, "synthetic", IMAGE)
            operation.assert_not_called()
            self.assertEqual(path.read_text(), "synthetic")
