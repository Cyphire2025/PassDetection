"""Offline release contracts for schema0099 -> schema0101; no VPS is contacted."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from release_import_groups_archive import (
    PREVIOUS_SCHEMA,
    SCHEMA,
    ImportGroupsArchiveRelease,
    main,
)
from release_reliability import DUMP_COMMAND, ReliabilityRelease
from release_traveller_whatsapp import ACTIVATED, WORKERS, ReleaseError
from test_release_notification_guard import RetainedArtifactDocker
from test_release_traveller_whatsapp import OLD_REVISION, REVISION


class ImportGroupsArchiveReleaseTests(unittest.TestCase):
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
        self.release = ImportGroupsArchiveRelease(REVISION, self.root)

    def test_prepare_activate_preserves_history_and_updates_all_application_services(self):
        self.release.prepare()
        self.assertEqual((self.root / ".env").read_text(), self.original_env)
        self.assertFalse(self.fake.commands("up"))
        previous = self.release.previous_images_path.read_bytes()
        self.release.activate()
        records = json.loads(self.release.backups_path.read_text())["backups"]
        self.assertEqual([item["schema"] for item in records], ["0099_gc_group_access_removal"])
        self.assertTrue(self.fake.assert_full_decode)
        self.assertEqual(self.fake.schema, "0101_client_group_import_only")
        self.assertEqual(self.fake.commands("upgrade")[0][-1], SCHEMA)
        self.assertEqual(set(json.loads(self.release.pin_path.read_text())["services"]), set(ACTIVATED))
        activations = self.fake.commands("up")
        self.assertTrue(set(WORKERS).issubset(activations[0]))
        self.assertEqual([call[-1] for call in activations[1:]], ["backend", "frontend"])
        self.assertEqual(self.release.previous_images_path.read_bytes(), previous)
        self.assertEqual((self.root / ".env").read_text(), self.original_env.replace(OLD_REVISION, REVISION).replace(PREVIOUS_SCHEMA, SCHEMA))
        self.assertEqual((self.release.directory / f"{REVISION}.env.backup").read_text(), self.original_env)
        self.assertFalse(any(set(call) & {"rm", "prune", "down", "downgrade", "purge", "reset"} for call in self.fake.calls))
        self.assertTrue(all("--rm" not in call for call in self.fake.commands("run")))
        self.assertIn("RELEASE VERIFIED", self.output.getvalue())
        self.assertNotIn("not-for-output", self.output.getvalue())

    def test_all_backup_validation_failures_stop_before_migration_and_activation(self):
        self.release.prepare()
        for failure in ("dump", "list", "decode", "copy"):
            with self.subTest(failure=failure):
                self.fake.backup_failure = failure
                with self.assertRaises(ReleaseError):
                    self.release.activate()
                self.assertEqual((self.root / ".env").read_text(), self.original_env)
                self.assertFalse(self.fake.commands("upgrade"))
                self.assertFalse(self.fake.commands("up"))
                self.assertFalse(self.release.backups_path.exists())

    def test_unexpected_or_partial_schema_never_triggers_broader_migration(self):
        self.release.prepare()
        for schema in ("0098_notification_saved_delete", "0100_whatsapp_group_archive", "0102_future"):
            with self.subTest(schema=schema):
                self.fake.schema = schema
                with self.assertRaisesRegex(ReleaseError, "no broader migration"):
                    self.release.activate()
                self.assertEqual((self.root / ".env").read_text(), self.original_env)
                self.assertFalse(self.fake.commands(DUMP_COMMAND))
                self.assertFalse(self.fake.commands("upgrade"))
                self.assertFalse(self.fake.commands("up"))

    def test_busy_workers_stop_before_backup_or_migration(self):
        self.release.prepare()
        for method in ("active", "reserved", "scheduled"):
            with self.subTest(method=method):
                self.fake.probe_method = method
                self.fake.busy_on_probe = self.fake.probe_count + 1
                with self.assertRaisesRegex(ReleaseError, "busy"):
                    self.release.activate()
                self.assertEqual((self.root / ".env").read_text(), self.original_env)
                self.assertFalse(self.fake.commands(DUMP_COMMAND))
                self.assertFalse(self.fake.commands("upgrade"))
                self.assertFalse(self.fake.commands("up"))

    def test_retry_retains_original_pre_migration_backup_and_rechecks_workers(self):
        self.release.prepare()
        self.fake.busy_on_probe = self.fake.probe_count + 2
        with self.assertRaisesRegex(ReleaseError, "busy"):
            self.release.activate()
        original = self.release.backups_path.read_bytes()
        self.assertEqual(self.fake.schema, SCHEMA)
        self.assertFalse(self.fake.commands("up"))
        self.fake.busy_on_probe = 0
        self.release.activate()
        self.assertEqual(original, self.release.backups_path.read_bytes())
        self.assertEqual(len(self.fake.commands(DUMP_COMMAND)), 1)

    def test_applied_schema_without_original_backup_refuses_activation(self):
        self.release.prepare()
        self.fake.schema = SCHEMA
        with self.assertRaisesRegex(ReleaseError, "pre-migration backup evidence is missing"):
            self.release.activate()
        self.assertFalse(self.fake.commands("upgrade"))
        self.assertFalse(self.fake.commands("up"))

    def test_optional_apns_overlay_is_included_only_when_enabled(self):
        for enabled in ("true", "1", True, "false", "0", False):
            with self.subTest(enabled=enabled):
                config = {"services": {"worker": {"environment": {"MOBILE_PUSH_APNS_ENABLED": enabled}}}}
                with (
                    patch.object(ReliabilityRelease, "preflight", return_value=config),
                    patch.object(self.release, "dc", return_value=json.dumps(config)) as compose,
                ):
                    self.release.compose = ["docker", "compose", "-p", "test", "-f", "docker-compose.yml", "-f", "docker-compose.prod.yml"]
                    self.assertEqual(self.release.preflight(), config)
                    if enabled in ("true", "1", True):
                        self.assertEqual(self.release.compose[-2:], ["-f", "docker-compose.apns.yml"])
                        compose.assert_called_once_with("config", "--format", "json")
                    else:
                        self.assertNotIn("docker-compose.apns.yml", self.release.compose)
                        compose.assert_not_called()

    def test_cli_requires_explicit_traffic_pause_before_any_activation_command(self):
        errors = io.StringIO()
        with (
            patch("sys.argv", ["release_import_groups_archive.py", "activate", "--revision", REVISION]),
            redirect_stderr(errors),
        ):
            self.assertEqual(main(), 1)
        self.assertIn("Pause new uploads and message sends", errors.getvalue())
        self.assertFalse(self.fake.calls)


if __name__ == "__main__":
    unittest.main()
