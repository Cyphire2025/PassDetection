"""Release0098 must retain history/backups and include the redesigned dashboard."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from release_notification_workspace import (
    PREVIOUS_SCHEMA,
    SCHEMA,
    NotificationWorkspaceRelease,
)
from release_reliability import DUMP_COMMAND, ReliabilityRelease
from release_traveller_whatsapp import ACTIVATED, ReleaseError
from test_release_notification_guard import RetainedArtifactDocker
from test_release_traveller_whatsapp import OLD_REVISION, REVISION


class NotificationWorkspaceReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.original_env = (
            f"APP_REVISION={OLD_REVISION}\nEXPECTED_DATABASE_SCHEMA_REVISION={PREVIOUS_SCHEMA}\n"
            "MOBILE_PUSH_PROVIDER=fcm\nPRIVATE_VALUE=not-for-output\n"
        )
        (self.root / ".env").write_text(self.original_env)
        self.fake = RetainedArtifactDocker(self.root)
        self.fake.expected_schema, self.fake.schema = SCHEMA, PREVIOUS_SCHEMA
        patcher = patch("release_traveller_whatsapp.subprocess.run", side_effect=self.fake.run)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.output = io.StringIO()
        redirector = redirect_stdout(self.output)
        redirector.__enter__()
        self.addCleanup(redirector.__exit__, None, None, None)
        self.release = NotificationWorkspaceRelease(REVISION, self.root)

    def test_prepare_activate_preserves_history_artifacts_and_provider_configuration(self):
        self.release.prepare()
        self.assertEqual((self.root / ".env").read_text(), self.original_env)
        self.assertFalse(self.fake.commands("up"))
        self.release.activate()
        backups = json.loads(self.release.backups_path.read_text())["backups"]
        self.assertEqual([item["schema"] for item in backups], ["0097_authored_notifications"])
        self.assertEqual(self.fake.schema, "0098_notification_saved_delete")
        self.assertEqual(self.fake.commands("upgrade")[0][-1], SCHEMA)
        self.assertEqual(set(json.loads(self.release.pin_path.read_text())["services"]), set(ACTIVATED))
        self.assertIn("frontend", self.release.activated_services)
        self.assertEqual((self.root / ".env").read_text(), self.original_env.replace(OLD_REVISION, REVISION).replace(PREVIOUS_SCHEMA, SCHEMA))
        self.assertFalse(any(set(call) & {"rm", "prune", "down", "downgrade", "purge", "reset"} for call in self.fake.calls))
        self.assertTrue(all("--rm" not in call for call in self.fake.commands("run")))
        self.assertIn("RELEASE VERIFIED", self.output.getvalue())
        self.assertNotIn("not-for-output", self.output.getvalue())

    def test_failed_backup_stops_before_migration_or_activation(self):
        self.release.prepare()
        self.fake.backup_failure = "decode"
        with self.assertRaises(ReleaseError):
            self.release.activate()
        self.assertEqual((self.root / ".env").read_text(), self.original_env)
        self.assertFalse(self.fake.commands("upgrade"))
        self.assertFalse(self.fake.commands("up"))

    def test_retry_retains_original_pre_migration_backup(self):
        self.release.prepare()
        self.fake.busy_on_probe = self.fake.probe_count + 2
        with self.assertRaisesRegex(ReleaseError, "busy"):
            self.release.activate()
        original = self.release.backups_path.read_bytes()
        self.assertEqual(self.fake.schema, SCHEMA)
        self.fake.busy_on_probe = 0
        self.release.activate()
        self.assertEqual(original, self.release.backups_path.read_bytes())
        self.assertEqual(len(self.fake.commands(DUMP_COMMAND)), 1)

    def test_optional_apns_overlay_is_preserved(self):
        config = {"services": {"worker": {"environment": {"MOBILE_PUSH_APNS_ENABLED": "true"}}}}
        with (
            patch.object(ReliabilityRelease, "preflight", return_value=config),
            patch.object(self.release, "dc", return_value=json.dumps(config)) as compose,
        ):
            self.release.compose = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.prod.yml"]
            self.assertEqual(self.release.preflight(), config)
            self.assertEqual(self.release.compose[-2:], ["-f", "docker-compose.apns.yml"])
            compose.assert_called_once_with("config", "--format", "json")


if __name__ == "__main__":
    unittest.main()
