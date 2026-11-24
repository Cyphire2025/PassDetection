"""Execute shared release orchestration using synthetic records and local mocks."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import release_retained_update as facade
import retained_release_lifecycle as lifecycle
from test_release_retained_update import NEXT, live_rows


class RetainedManifestAdmission(unittest.TestCase):
    def execute(self, mode, artifact):
        release = object.__new__(facade.RetainedUpdate)
        with tempfile.TemporaryDirectory() as directory:
            release.directory = Path(directory)
            release.source = Path(directory) / "source"
            release.revision = NEXT
            release.project = "synthetic-project"
            release.mode = mode
            release.artifact = artifact
            release.pause_email_and_photos = False
            rows = live_rows()
            for row in rows:
                row["HostConfig"] = {"Memory": 1024 * 1024}
            release.rows = Mock(return_value=rows)
            release.compatibility = Mock()
            release.current_main = Mock()
            release.event = Mock()
            release.schema = Mock(return_value=facade.SCHEMA)
            release.proof = Mock()
            release.prepare_images = Mock()
            release.backup = Mock()
            release.stage = Mock(return_value={"synthetic": "candidates"})
            release.transition = Mock()
            images = {"backend": "synthetic-backend", "frontend": "synthetic-frontend"}
            release.fast_images = Mock(return_value=images)
            manifest = {
                "schema": facade.SCHEMA,
                "images": {name: {"local_image_id": value} for name, value in images.items()},
            }

            def verify(path, *args, **kwargs):
                if path is None:
                    raise TypeError("synthetic missing manifest path")
                return manifest

            with (
                patch.object(
                    lifecycle.Path, "read_text", return_value="Filename Type Size Used Priority\n"
                ),
                patch.object(
                    lifecycle.shutil,
                    "disk_usage",
                    return_value=SimpleNamespace(free=20 * facade.GIB),
                ),
                patch.object(lifecycle, "command", return_value=str(16 * facade.GIB)),
                patch.object(lifecycle, "verify_manifest", side_effect=verify) as verifier,
            ):
                self.verifier = verifier
                release.run()
            release.backup.assert_called_once_with()
            release.stage.assert_called_once_with(images)
            release.transition.assert_called_once_with({"synthetic": "candidates"})
            return verifier, release.fast_images

    def test_full_preserves_signed_manifest_call_and_uses_verified_images(self):
        path = Path("synthetic-manifest.json")
        verifier, fast = self.execute("full", path)
        verifier.assert_called_once_with(path, NEXT, pull=True, enforce_current_policy=True)
        fast.assert_not_called()

    def test_fast_preserves_build_path_without_signed_manifest_call(self):
        verifier, fast = self.execute("fast", None)
        verifier.assert_not_called()
        fast.assert_called_once_with()

    def test_missing_full_manifest_fails_with_existing_constructor_reason(self):
        with self.assertRaisesRegex(ValueError, "^full_requires_manifest_fast_forbids_manifest$"):
            self.execute("full", None)
        self.verifier.assert_not_called()


if __name__ == "__main__":
    unittest.main()
