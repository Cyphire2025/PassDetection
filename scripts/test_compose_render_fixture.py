"""Compose source qualification must not depend on a private .env file."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import verify_compose_runtime as compose


class ComposeRenderFixtureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.example = b"APP_ENV=development\nPOSTGRES_PASSWORD=synthetic-fixture\n"
        (self.root / ".env.example").write_bytes(self.example)
        self.source = self.root / "compose.yml"
        self.source.write_text("services: {}\n")
        self.fixture = None

    def render(self, returncode=0):
        def process(command, **options):
            self.fixture = Path(command[command.index("--env-file") + 1])
            self.assertNotEqual(self.fixture.parent, self.root)
            self.assertEqual(self.fixture.read_bytes(), self.example)
            self.assertEqual(command[command.index("--project-directory") + 1], str(self.fixture.parent))
            self.assertEqual(command[command.index("-f") + 1], str(self.source))
            self.assertEqual(command[-4:], ["config", "--format", "json", "--no-env-resolution"])
            self.assertNotIn("--no-consistency", command)
            self.assertNotIn("up", command)
            return subprocess.CompletedProcess(
                command, returncode, stdout=json.dumps({"services": {}}), stderr="synthetic render failure"
            )

        with patch.object(compose, "ROOT", self.root), patch.object(compose.subprocess, "run", side_effect=process):
            return compose._render_compose(self.source)

    def test_clean_checkout_renders_without_creating_repository_env(self):
        self.assertEqual(self.render(), {"services": {}})
        self.assertFalse((self.root / ".env").exists())
        self.assertFalse(self.fixture.exists())

    def test_existing_private_environment_is_not_read_or_replaced(self):
        private = self.root / ".env"
        private.write_bytes(b"PRIVATE_VALUE=must-remain-private\n")
        self.assertEqual(self.render(), {"services": {}})
        self.assertEqual(private.read_bytes(), b"PRIVATE_VALUE=must-remain-private\n")
        self.assertFalse(self.fixture.exists())

    def test_render_failure_is_not_ignored_and_cleans_fixture(self):
        with self.assertRaisesRegex(RuntimeError, "synthetic render failure"):
            self.render(returncode=1)
        self.assertFalse(self.fixture.exists())
        self.assertFalse((self.root / ".env").exists())


if __name__ == "__main__":
    unittest.main()
