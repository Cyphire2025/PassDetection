"""Shared operator admission boundaries with synthetic Compose/image JSON only."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from release_traveller_whatsapp import ACTIVATED, Release, ReleaseError


class ReleaseJsonBoundaries(unittest.TestCase):
    def preflight(self, document):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("SYNTHETIC_QUALIFICATION_ONLY=1\n", encoding="utf-8")
            release = object.__new__(Release)
            release.root = root
            release.compose = ["docker", "compose", "-p", "synthetic"]
            release.activated_services = ACTIVATED
            release.verify_checkout = Mock()
            release.verify_running_project = Mock()
            release.dc = Mock(return_value=json.dumps(document))
            result = release.preflight()
            release.verify_checkout.assert_called_once_with()
            release.verify_running_project.assert_called_once_with()
            release.dc.assert_called_once_with("config", "--format", "json")
            return result

    def test_normal_compose_object_preserves_every_existing_field(self):
        document = {
            "name": "synthetic",
            "services": {name: {"image": "synthetic-image"} for name in (*ACTIVATED, "nginx")},
            "extra": {"preserved": True},
        }
        self.assertEqual(self.preflight(document), document)

    def test_non_object_compose_json_fails_as_bounded_release_error(self):
        for document in (None, [], "synthetic-invalid", 42):
            with self.subTest(document=document):
                with self.assertRaises(ReleaseError) as error:
                    self.preflight(document)
                self.assertIn("missing required release services", str(error.exception))
                self.assertNotIn("synthetic-invalid", str(error.exception))

    def test_normal_image_id_is_returned_without_coercing_other_metadata(self):
        release = object.__new__(Release)
        image_id = "sha256:" + "a" * 64
        release.inspect = Mock(return_value={"Id": image_id, "extra": "synthetic"})
        self.assertEqual(release.verify_image("synthetic-image", backend=False), image_id)
        release.inspect.assert_called_once_with("synthetic-image", image=True)

    def test_non_string_image_identifiers_fail_as_bounded_release_error(self):
        for image_id in (None, 42, {"private": "synthetic-invalid"}):
            release = object.__new__(Release)
            release.inspect = Mock(return_value={"Id": image_id})
            with self.subTest(image_id=image_id):
                with self.assertRaises(ReleaseError) as error:
                    release.verify_image("synthetic-image", backend=False)
                self.assertEqual(str(error.exception), "Docker returned an invalid image ID")


if __name__ == "__main__":
    unittest.main()
