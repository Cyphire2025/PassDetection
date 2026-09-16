"""The startup fix is a data-preserving, backend-only release on schema 0098."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from release_realtime_startup import SCHEMA, RealtimeStartupRelease
from release_reliability import DUMP_COMMAND, ReliabilityRelease
from release_traveller_whatsapp import ACTIVATED, ReleaseError
from test_release_notification_guard import RetainedArtifactDocker
from test_release_traveller_whatsapp import OLD_REVISION, REVISION


class RealtimeStartupReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.original_env = (
            f"APP_REVISION={OLD_REVISION}\nEXPECTED_DATABASE_SCHEMA_REVISION={SCHEMA}\n"
            "MOBILE_PUSH_PROVIDER=fcm\nPRIVATE_VALUE=not-for-output\n"
        )
        (self.root / ".env").write_text(self.original_env)
        self.fake = RetainedArtifactDocker(self.root)
        self.fake.expected_schema = self.fake.schema = SCHEMA
        patcher = patch("release_traveller_whatsapp.subprocess.run", side_effect=self.fake.run)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.output = io.StringIO()
        redirector = redirect_stdout(self.output)
        redirector.__enter__()
        self.addCleanup(redirector.__exit__, None, None, None)
        self.release = RealtimeStartupRelease(REVISION, self.root)

    def test_activation_retains_schema_artifacts_and_frontend(self):
        self.release.prepare()
        self.assertEqual((self.root / ".env").read_text(), self.original_env)
        self.assertFalse(self.fake.commands("up"))
        self.release.activate()
        self.assertEqual(self.fake.schema, SCHEMA)
        self.assertEqual(set(json.loads(self.release.pin_path.read_text())["services"]), set(ACTIVATED) - {"frontend"})
        self.assertTrue(all("frontend" not in command for command in self.fake.commands("build") + self.fake.commands("up")))
        self.assertEqual((self.root / ".env").read_text(), self.original_env.replace(OLD_REVISION, REVISION))
        self.assertFalse(any(set(call) & {"rm", "prune", "down", "downgrade", "purge", "reset"} for call in self.fake.calls))
        self.assertTrue(all("--rm" not in call for call in self.fake.commands("run")))
        self.assertNotIn("not-for-output", self.output.getvalue())

    def test_each_activation_captures_a_fresh_verified_backup(self):
        self.release.prepare()
        self.release.activate()
        self.release.activate()
        records = json.loads(self.release.backups_path.read_text())["backups"]
        self.assertEqual(len(records), 2)
        self.assertNotEqual(records[0]["filename"], records[1]["filename"])
        self.assertTrue(all(record["schema"] == SCHEMA for record in records))
        self.assertEqual(len(self.fake.commands(DUMP_COMMAND)), 2)

    def test_bad_backup_stops_before_activation(self):
        self.release.prepare()
        self.fake.backup_failure = "decode"
        with self.assertRaises(ReleaseError):
            self.release.activate()
        self.assertFalse(self.fake.commands("upgrade"))
        self.assertFalse(self.fake.commands("up"))
        self.assertEqual((self.root / ".env").read_text(), self.original_env)

    def test_optional_apns_mount_configuration_is_kept(self):
        config = {"services": {"worker": {"environment": {"MOBILE_PUSH_APNS_ENABLED": "true"}}}}
        with (
            patch.object(ReliabilityRelease, "preflight", return_value=config),
            patch.object(self.release, "dc", return_value=json.dumps(config)),
        ):
            self.release.compose = ["docker", "compose", "-f", "docker-compose.yml"]
            self.assertEqual(self.release.preflight(), config)
            self.assertEqual(self.release.compose[-2:], ["-f", "docker-compose.apns.yml"])


if __name__ == "__main__":
    unittest.main()
