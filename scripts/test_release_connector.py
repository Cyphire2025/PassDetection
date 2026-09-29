"""Reject changed package bytes, widened inventories, and source substitutions."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from release_connector import MANIFEST, package, source_files, verify, verify_bytes


class ConnectorReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "source"
        self.output = Path(self.temporary.name) / "release"
        project = self.root / "mcp-connector"
        project.mkdir(parents=True)
        (project / "pyproject.toml").write_text('[project]\nname="global-connects-mcp-connector"\nversion="0.2.0"\nrequires-python=">=3.11,<3.12"\n')
        for name, path in source_files(self.root).items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic " + name)
        self.revision = "a" * 40
        self.manifest = package(self.output, self.revision, self.root)

    def test_exact_bytes_and_source_contract_round_trip(self):
        self.assertEqual(verify_bytes(self.output, self.revision, self.root), self.manifest)
        self.assertFalse(self.manifest["interactive_sign_in_qualified"])
        with self.assertRaisesRegex(ValueError, "replace"):
            package(self.output, self.revision, self.root)

    def test_tampered_wheel_or_lock_or_instructions_fail(self):
        for name in self.manifest["files"]:
            path = self.output / name
            original = path.read_bytes()
            path.write_bytes(original + b"tampered")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "checksum"):
                verify_bytes(self.output, self.revision, self.root)
            path.write_bytes(original)

    def test_widened_inventory_commit_and_claims_fail(self):
        path = self.output / MANIFEST
        for field, value in (("revision", "b" * 40), ("version", True),
                             ("interactive_sign_in_qualified", True),
                             ("files", {"../../outside.whl": {"sha256": "0" * 64, "size_bytes": 4}})):
            changed = {**self.manifest, field: value}
            path.write_text(json.dumps(changed))
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_bytes(self.output, self.revision, self.root)
        path.write_text(json.dumps(self.manifest))
        source_files(self.root)["connector-requirements.lock"].write_text("different source lock")
        with self.assertRaisesRegex(ValueError, "source commit"):
            verify_bytes(self.output, self.revision, self.root)

    def test_signature_is_required_before_inventory_interpretation(self):
        (self.output / MANIFEST).write_text("not-json")
        with patch("release_connector.run", side_effect=RuntimeError("untrusted signature")) as runner, self.assertRaisesRegex(RuntimeError, "untrusted signature"):
            verify(self.output, self.revision)
        arguments = runner.call_args.args
        self.assertIn("--deny-self-hosted-runners", arguments)
        self.assertEqual(arguments[arguments.index("--source-digest") + 1], self.revision)


if __name__ == "__main__":
    unittest.main()
