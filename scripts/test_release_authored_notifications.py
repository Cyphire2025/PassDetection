"""Offline release checks for the additive authored notification migration."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from release_authored_notifications import AuthoredNotificationRelease, PREVIOUS_SCHEMA, SCHEMA
from release_reliability import DUMP_COMMAND, ReliabilityRelease
from release_traveller_whatsapp import ACTIVATED, ReleaseError
from test_release_notification_guard import RetainedArtifactDocker
from test_release_traveller_whatsapp import OLD_REVISION, REVISION


class AuthoredNotificationReleaseTests(unittest.TestCase):
    def test_enabled_apns_keeps_optional_read_only_mount_overlay_for_both_release_phases(self):
        config = {"services": {"worker": {"environment": {"MOBILE_PUSH_APNS_ENABLED": "true"}}}}
        with patch.object(ReliabilityRelease, "preflight", return_value=config):
            with patch.object(self.release, "dc", return_value=json.dumps(config)) as compose:
                self.release.compose = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.prod.yml"]
                assert self.release.preflight() == config
                assert self.release.compose[-2:] == ["-f", "docker-compose.apns.yml"]
                compose.assert_called_once_with("config", "--format", "json")

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
        self.release = AuthoredNotificationRelease(REVISION, self.root)

    def test_prepare_and_activate_retains_data_artifacts_and_provider_configuration(self):
        self.release.prepare()
        self.assertEqual((self.root / ".env").read_text(), self.original_env)
        self.assertFalse(self.fake.commands("up"))
        self.release.activate()
        backups = json.loads(self.release.backups_path.read_text())["backups"]
        self.assertEqual([item["schema"] for item in backups], ["0096_mobile_phone_lookup"])
        self.assertEqual(self.fake.schema, "0097_authored_notifications")
        upgrade = self.fake.commands("upgrade")[0]
        self.assertEqual(upgrade[-1], SCHEMA)
        self.assertLess(self.fake.calls.index(self.fake.commands("cp")[0]), self.fake.calls.index(upgrade))
        self.assertEqual(set(json.loads(self.release.pin_path.read_text())["services"]), set(ACTIVATED))
        self.assertEqual((self.root / ".env").read_text(), self.original_env.replace(OLD_REVISION, REVISION).replace(PREVIOUS_SCHEMA, SCHEMA))
        self.assertFalse(any(set(call) & {"rm", "prune", "down", "downgrade", "purge", "reset"} for call in self.fake.calls))
        self.assertTrue(all("--rm" not in call for call in self.fake.commands("run")))
        self.assertIn("RELEASE VERIFIED", self.output.getvalue())
        self.assertNotIn("not-for-output", self.output.getvalue())

    def test_retry_requires_original_same_revision_pre_migration_backup(self):
        self.release.prepare()
        self.fake.schema = SCHEMA
        with self.assertRaisesRegex(ReleaseError, "pre-migration backup evidence is missing"):
            self.release.activate()
        self.assertFalse(self.fake.commands("up"))
        self.fake.schema = PREVIOUS_SCHEMA
        self.fake.busy_on_probe = self.fake.probe_count + 2
        with self.assertRaisesRegex(ReleaseError, "busy"):
            self.release.activate()
        backup_before = self.release.backups_path.read_bytes()
        self.assertEqual(self.fake.schema, SCHEMA)
        self.fake.busy_on_probe = 0
        self.release.activate()
        self.assertEqual(self.release.backups_path.read_bytes(), backup_before)
        self.assertEqual(len(self.fake.commands(DUMP_COMMAND)), 1)

    def test_failed_backup_prevents_any_schema_or_service_change(self):
        self.release.prepare()
        self.fake.backup_failure = "decode"
        with self.assertRaises(ReleaseError):
            self.release.activate()
        self.assertEqual((self.root / ".env").read_text(), self.original_env)
        self.assertFalse(self.fake.commands("upgrade"))
        self.assertFalse(self.fake.commands("up"))


if __name__ == "__main__":
    unittest.main()
