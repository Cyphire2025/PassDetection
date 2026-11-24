"""Shared release input boundaries with synthetic local files and no services."""

import json
import tempfile
import unittest
from pathlib import Path

from image_runtime_policy import reviewed_process_command, validate_process_command
from release_manifest import load_release_manifest


class SharedOperatorJsonBoundaries(unittest.TestCase):
    def manifest(self, value):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            return load_release_manifest(path)

    def valid_manifest(self):
        return {
            "version": 1,
            "schema_revision": "0142_group_background",
            "previous_schema_revision": "0140_agency_credential_fences",
            "worker_nodes": {"worker": "general"},
            "extra": {"retained": True},
        }

    def test_normal_manifest_preserves_all_values(self):
        value = self.valid_manifest()
        self.assertEqual(self.manifest(value), value)

    def test_non_object_manifest_has_bounded_existing_rejection(self):
        for value in (None, [], 42, "synthetic-private"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "^Unsupported release manifest$"):
                    self.manifest(value)

    def test_non_string_revision_has_bounded_existing_rejection(self):
        for key in ("schema_revision", "previous_schema_revision"):
            for value in (None, 42, ["synthetic-private"]):
                with self.subTest(key=key, value=value):
                    document = self.valid_manifest()
                    document[key] = value
                    with self.assertRaisesRegex(ValueError, f"^Invalid release manifest {key}$"):
                        self.manifest(document)

    def test_normal_worker_command_keeps_reviewed_queue_and_executable(self):
        command = reviewed_process_command("worker", concurrency=2)
        validate_process_command("worker", {"command": command})
        self.assertIn("--concurrency=2 -Q passport_ocr,whatsapp", command[2])

    def test_non_string_worker_shell_program_has_existing_bounded_rejection(self):
        for program in (None, 42, ["synthetic-private"]):
            with self.subTest(program=program):
                with self.assertRaisesRegex(ValueError, "^worker: unreviewed worker command$"):
                    validate_process_command("worker", {"command": ["sh", "-c", program]})


if __name__ == "__main__":
    unittest.main()
