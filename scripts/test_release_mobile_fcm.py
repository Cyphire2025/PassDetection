"""Offline FCM migration/release checks; all subprocess calls are faked."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from release_mobile_fcm import PREVIOUS_SCHEMA, SCHEMA, MobileFcmRelease, main
from release_notification_guard import NotificationGuardRelease
from release_reliability import DUMP_COMMAND, ReliabilityRelease
from release_traveller_whatsapp import ACTIVATED, WORKERS, Release, ReleaseError
from test_release_notification_guard import RetainedArtifactDocker
from test_release_reliability import DUMP
from test_release_traveller_whatsapp import OLD_IMAGE, OLD_REVISION, REVISION


class MobileFcmReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.original_env = (
            f"PASSWORD=private-test-value\nAPP_REVISION={OLD_REVISION}\n"
            f"EXPECTED_DATABASE_SCHEMA_REVISION={PREVIOUS_SCHEMA}\n"
            "MOBILE_PUSH_PROVIDER=disabled\n"
        )
        (self.root / ".env").write_text(self.original_env)
        self.fake = RetainedArtifactDocker(self.root)
        self.fake.expected_schema = SCHEMA
        self.fake.schema = PREVIOUS_SCHEMA
        patcher = patch("release_traveller_whatsapp.subprocess.run", side_effect=self.fake.run)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.output = io.StringIO()
        redirector = redirect_stdout(self.output)
        redirector.__enter__()
        self.addCleanup(redirector.__exit__, None, None, None)
        self.release = MobileFcmRelease(REVISION, self.root)

    def backup_records(self):
        return json.loads(self.release.backups_path.read_text())["backups"]

    def migrate_then_pause_activation(self):
        self.release.prepare()
        self.fake.busy_on_probe = 2
        with self.assertRaisesRegex(ReleaseError, "busy"):
            self.release.activate()
        self.assertEqual(self.fake.schema, SCHEMA)
        self.assertFalse(self.fake.commands("up"))
        self.fake.busy_on_probe = 0

    def test_complete_release_backs_up_0094_then_activates_all_prepared_services(self):
        self.release.prepare()
        self.assertEqual((self.root / ".env").read_text(), self.original_env)
        self.assertFalse(self.fake.commands(DUMP_COMMAND))
        self.assertFalse(self.fake.commands("up"))
        self.assertEqual(self.fake.commands("build")[0][-3:], ["backend", "worker", "frontend"])
        previous = json.loads(self.release.previous_images_path.read_text())
        self.assertEqual(set(previous["services"]), set(ACTIVATED))
        self.assertTrue(all(item["image_id"] == OLD_IMAGE for item in previous["services"].values()))
        self.release.activate()
        records = self.backup_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["schema"], PREVIOUS_SCHEMA)
        self.assertEqual((self.release.directory / records[0]["filename"]).read_bytes(), DUMP)
        self.assertTrue(self.fake.assert_full_decode)
        self.assertFalse(records[0]["restore_rehearsed"])
        self.assertEqual(self.fake.schema, SCHEMA)
        upgrades = self.fake.commands("upgrade")
        self.assertEqual(len(upgrades), 1)
        self.assertEqual(upgrades[0][-1], SCHEMA)
        self.assertLess(self.fake.calls.index(self.fake.commands("cp")[0]), self.fake.calls.index(upgrades[0]))
        activations = self.fake.commands("up")
        self.assertEqual(len(activations), 3)
        self.assertEqual(activations[0][-len(WORKERS):], list(WORKERS))
        self.assertEqual(activations[1][-1], "backend")
        self.assertEqual(activations[2][-1], "frontend")
        self.assertLess(self.fake.calls.index(upgrades[0]), self.fake.calls.index(activations[0]))
        self.assertTrue(all("--no-deps" in call and "--no-build" in call for call in activations))
        self.assertFalse(any(set(call) & {"db", "redis", "nginx", "minio"} for call in activations))
        self.assertEqual(set(json.loads(self.release.pin_path.read_text())["services"]), set(ACTIVATED))
        self.assertEqual(self.fake.probe_count, 2)
        self.assertEqual(len(self.fake.commands("curl")), 2)
        self.assertEqual(
            (self.root / ".env").read_text(),
            self.original_env.replace(OLD_REVISION, REVISION).replace(PREVIOUS_SCHEMA, SCHEMA),
        )
        self.assertEqual((self.release.directory / f"{REVISION}.env.backup").read_text(), self.original_env)
        self.assertIn(
            f"RELEASE VERIFIED: {REVISION}; schema {SCHEMA}; backend, frontend, seven workers and beat.",
            self.output.getvalue(),
        )
        self.assertNotIn("private-test-value", self.output.getvalue())

    def test_existing_release_defaults_and_scopes_are_unchanged(self):
        legacy = Release(REVISION, self.root)
        reliability = ReliabilityRelease(REVISION, self.root)
        guard = NotificationGuardRelease(REVISION, self.root)
        self.assertEqual((legacy.previous_schema, legacy.expected_schema), ("0092_whatsapp_matching_fields", "0093_phone_welcome"))
        self.assertEqual((reliability.previous_schema, reliability.expected_schema), ("0093_phone_welcome", PREVIOUS_SCHEMA))
        self.assertEqual((guard.previous_schema, guard.expected_schema), (PREVIOUS_SCHEMA, PREVIOUS_SCHEMA))
        self.assertEqual(legacy.activated_services, ACTIVATED)
        self.assertEqual(reliability.activated_services, ACTIVATED)
        self.assertNotIn("frontend", guard.activated_services)
        self.assertEqual(self.release.activated_services, ACTIVATED)
        self.assertFalse(legacy.preserve_release_artifacts)
        self.assertFalse(reliability.preserve_release_artifacts)
        self.assertTrue(guard.preserve_release_artifacts)
        self.assertTrue(self.release.preserve_release_artifacts)
        self.assertEqual(len({release.directory for release in (legacy, reliability, guard, self.release)}), 4)
        self.assertEqual({release.lock_directory for release in (legacy, reliability, guard, self.release)}, {self.release.lock_directory})
        with self.assertRaises(ReleaseError):
            ReliabilityRelease(REVISION, self.root, expected_schema="head; unsafe")

    def test_other_schemas_are_rejected_without_broad_migration(self):
        self.release.prepare()
        for schema in ("0093_phone_welcome", "0096_future"):
            with self.subTest(schema=schema):
                self.fake.schema = schema
                with self.assertRaisesRegex(ReleaseError, "no broader migration"):
                    self.release.activate()
                self.assertEqual((self.root / ".env").read_text(), self.original_env)
                self.assertFalse(self.fake.commands(DUMP_COMMAND))
                self.assertFalse(self.fake.commands("upgrade"))
                self.assertFalse(self.fake.commands("up"))

    def test_existing_0095_without_same_commit_pre_migration_evidence_is_rejected(self):
        self.fake.schema = SCHEMA
        self.release.prepare()
        with self.assertRaisesRegex(ReleaseError, "pre-migration backup evidence is missing"):
            self.release.activate()
        self.assertFalse(self.fake.commands(DUMP_COMMAND))
        self.assertFalse(self.fake.commands("upgrade"))
        self.assertFalse(self.fake.commands("up"))
        self.assertEqual((self.root / ".env").read_text(), self.original_env)

    def test_same_commit_retry_preserves_0094_backup_and_original_recovery_images(self):
        self.migrate_then_pause_activation()
        backups_before = self.release.backups_path.read_bytes()
        images_before = self.release.previous_images_path.read_bytes()
        environment_before = (self.release.directory / f"{REVISION}.env.backup").read_bytes()
        self.release.prepare()
        self.release.activate()
        self.assertEqual(self.release.backups_path.read_bytes(), backups_before)
        self.assertEqual(self.release.previous_images_path.read_bytes(), images_before)
        self.assertEqual((self.release.directory / f"{REVISION}.env.backup").read_bytes(), environment_before)
        self.assertEqual(len(self.fake.commands(DUMP_COMMAND)), 1)
        self.assertEqual(self.backup_records()[0]["schema"], PREVIOUS_SCHEMA)
        self.assertFalse(self.fake.commands("downgrade"))

    def test_corrupt_pre_migration_backup_blocks_retry_without_replacement_dump(self):
        self.migrate_then_pause_activation()
        record = self.backup_records()[0]
        (self.release.directory / record["filename"]).write_bytes(b"corrupted")
        with self.assertRaisesRegex(ReleaseError, "integrity validation"):
            self.release.activate()
        self.assertEqual(len(self.fake.commands(DUMP_COMMAND)), 1)
        self.assertEqual(len(self.fake.commands("upgrade")), 1)
        self.assertFalse(self.fake.commands("up"))

    def test_another_commit_cannot_supply_backup_evidence_for_a_0095_retry(self):
        self.migrate_then_pause_activation()
        evidence = json.loads(self.release.backups_path.read_text())
        evidence["revision"] = OLD_REVISION
        self.release.backups_path.write_text(json.dumps(evidence))
        with self.assertRaisesRegex(ReleaseError, "Recovery evidence does not match"):
            self.release.activate()
        self.assertEqual(len(self.fake.commands(DUMP_COMMAND)), 1)
        self.assertFalse(self.fake.commands("up"))

    def test_backup_failures_prevent_environment_migration_and_activation(self):
        self.release.prepare()
        for failure in ("dump", "list", "decode", "copy"):
            with self.subTest(failure=failure):
                self.fake.backup_failure = failure
                with self.assertRaises(ReleaseError):
                    self.release.activate()
                self.assertEqual((self.root / ".env").read_text(), self.original_env)
                self.assertFalse(self.fake.commands("upgrade"))
                self.assertFalse(self.fake.commands("up"))
                self.assertFalse(self.fake.commands("rm"))
                self.assertFalse(self.release.backups_path.exists())
        partials = list(self.release.directory.glob(".*.pgdump.partial"))
        self.assertEqual(len(partials), 1)
        self.assertEqual(partials[0].read_bytes(), b"corrupt-copy")

    def test_failed_migration_activates_nothing_and_retry_on_0094_takes_fresh_backup(self):
        self.release.prepare()
        self.fake.fail_migration = True
        with self.assertRaises(ReleaseError):
            self.release.activate()
        first = self.backup_records()[0]
        self.assertEqual(self.fake.schema, PREVIOUS_SCHEMA)
        self.assertFalse(self.fake.commands("up"))
        self.fake.fail_migration = False
        self.release.activate()
        records = self.backup_records()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0], first)
        self.assertNotEqual(records[0]["filename"], records[1]["filename"])
        self.assertTrue(all(record["schema"] == PREVIOUS_SCHEMA for record in records))
        self.assertFalse(self.fake.commands("downgrade"))

    def test_busy_workers_stop_before_backup_environment_or_code_change(self):
        self.release.prepare()
        self.fake.busy_on_probe = 1
        with self.assertRaisesRegex(ReleaseError, "busy"):
            self.release.activate()
        self.assertEqual((self.root / ".env").read_text(), self.original_env)
        self.assertFalse(self.fake.commands(DUMP_COMMAND))
        self.assertFalse(self.fake.commands("up"))

    def test_prepared_schema_mismatch_stops_before_backup(self):
        self.release.prepare()
        manifest = json.loads(self.release.manifest_path.read_text())
        manifest["schema"] = PREVIOUS_SCHEMA
        self.release.manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ReleaseError, "Prepared release does not match"):
            self.release.activate()
        self.assertFalse(self.fake.commands(DUMP_COMMAND))
        self.assertFalse(self.fake.commands("up"))

    def test_release_retains_temporary_archives_and_all_one_off_containers(self):
        self.release.prepare()
        self.release.activate()
        self.assertEqual(len(self.fake.commands("run")), 3)
        self.assertTrue(all("--rm" not in call and "--no-deps" in call for call in self.fake.commands("run")))
        self.assertFalse(any(
            set(call) & {"rm", "prune", "down", "downgrade", "kill", "purge", "reset", "stash"}
            for call in self.fake.calls
        ))
        remote = self.fake.commands(DUMP_COMMAND)[0][-1]
        self.assertIn(remote, self.output.getvalue())

    def test_failed_public_health_cannot_report_success(self):
        self.release.prepare()
        self.fake.public_status = "503"
        with self.assertRaisesRegex(ReleaseError, "did not return HTTP 200"):
            self.release.activate()
        self.assertNotIn("RELEASE VERIFIED", self.output.getvalue())

    def test_cli_requires_traffic_pause_before_any_subprocess(self):
        with (
            patch("sys.argv", ["release_mobile_fcm.py", "activate", "--revision", REVISION]),
            redirect_stderr(self.output),
        ):
            self.assertEqual(main(), 1)
        self.assertFalse(self.fake.calls)
        self.assertIn("--traffic-paused", self.output.getvalue())


if __name__ == "__main__":
    unittest.main()
