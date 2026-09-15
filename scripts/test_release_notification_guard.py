"""Offline same-schema release checks; all Docker/subprocess calls are faked."""

from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from release_notification_guard import NotificationGuardRelease, main
from release_reliability import (
    DUMP_COMMAND,
    PREVIOUS_SCHEMA,
    SCHEMA,
    ReliabilityRelease,
)
from release_traveller_whatsapp import ACTIVATED, WORKERS, Release, ReleaseError
from test_release_reliability import DUMP, RecoveryDocker
from test_release_traveller_whatsapp import (
    NEW_BACKEND,
    OLD_IMAGE,
    OLD_REVISION,
    REVISION,
)


class RetainedArtifactDocker(RecoveryDocker):
    """Accept retained one-off containers without weakening the original fake."""

    def run(self, args, **kwargs):
        args = list(args)
        tail = args[8:] if args[:2] == ["docker", "compose"] else []
        pin_path = None
        if tail[:1] == ["-f"]:
            pin_path = Path(tail[1])
            tail = tail[2:]
        if tail[:1] != ["run"] or "--rm" in tail:
            return super().run(args, **kwargs)
        self.calls.append(args)
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["env"]["APP_REVISION"] == REVISION
        assert kwargs["env"]["EXPECTED_DATABASE_SCHEMA_REVISION"] == self.expected_schema
        assert pin_path is not None and "--no-deps" in tail
        assert json.loads(pin_path.read_text())["services"]["backend"]["image"] == NEW_BACKEND
        code = 0
        output = ""
        if tail[-3:] == ["backend", "alembic", "current"]:
            output = self.schema + " (head)"
        elif tail[-4:] == ["backend", "alembic", "upgrade", self.expected_schema]:
            code = int(self.fail_migration)
            if not code:
                self.schema = self.expected_schema
        else:
            raise AssertionError(f"Unexpected retained one-off command: {tail}")
        return subprocess.CompletedProcess(args, code, stdout=output, stderr="private diagnostic")


class NotificationGuardReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.original_env = (
            f"PASSWORD=private-test-value\nAPP_REVISION={OLD_REVISION}\n"
            f"EXPECTED_DATABASE_SCHEMA_REVISION={SCHEMA}\n"
            "MOBILE_PUSH_PROVIDER=disabled\n"
        )
        (self.root / ".env").write_text(self.original_env)
        self.fake = RetainedArtifactDocker(self.root)
        self.fake.schema = SCHEMA
        patcher = patch("release_traveller_whatsapp.subprocess.run", side_effect=self.fake.run)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.output = io.StringIO()
        redirector = redirect_stdout(self.output)
        redirector.__enter__()
        self.addCleanup(redirector.__exit__, None, None, None)
        self.release = NotificationGuardRelease(REVISION, self.root)

    def test_same_schema_release_takes_fresh_backup_before_code_activation(self):
        self.release.prepare()
        self.assertEqual((self.root / ".env").read_text(), self.original_env)
        self.assertFalse(self.fake.commands(DUMP_COMMAND))
        self.assertFalse(self.fake.commands("up"))
        previous = json.loads(self.release.previous_images_path.read_text())
        self.assertEqual(set(previous["services"]), set(WORKERS) | {"backend"})
        self.assertTrue(all(item["image_id"] == OLD_IMAGE for item in previous["services"].values()))
        self.release.activate()
        records = json.loads(self.release.backups_path.read_text())["backups"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["schema"], SCHEMA)
        self.assertEqual((self.release.directory / records[0]["filename"]).read_bytes(), DUMP)
        self.assertTrue(self.fake.assert_full_decode)
        self.assertEqual(self.fake.schema, SCHEMA)
        self.assertEqual(self.fake.commands("upgrade")[0][-1], SCHEMA)
        self.assertEqual(len(self.fake.commands("upgrade")), 1)
        self.assertLess(self.fake.calls.index(self.fake.commands("cp")[0]), self.fake.calls.index(self.fake.commands("upgrade")[0]))
        self.assertLess(self.fake.calls.index(self.fake.commands("upgrade")[0]), self.fake.calls.index(self.fake.commands("up")[0]))
        self.assertEqual(self.fake.probe_count, 2)
        self.assertEqual(len(self.fake.commands("curl")), 2)
        self.assertIn("MOBILE_PUSH_PROVIDER=disabled", (self.root / ".env").read_text())
        self.assertIn("BACKUP VERIFIED", self.output.getvalue())
        self.assertIn("RELEASE VERIFIED", self.output.getvalue())
        self.assertNotIn("private-test-value", self.output.getvalue())
        self.assertFalse(any(set(call) & {"downgrade", "down", "kill", "purge", "reset", "stash"} for call in self.fake.calls))

    def test_only_existing_0094_is_accepted_before_backup_or_activation(self):
        self.release.prepare()
        for schema in (PREVIOUS_SCHEMA, "0092_whatsapp_matching_fields", "0095_future"):
            with self.subTest(schema=schema):
                self.fake.schema = schema
                with self.assertRaisesRegex(ReleaseError, "no broader migration"):
                    self.release.activate()
                self.assertEqual((self.root / ".env").read_text(), self.original_env)
                self.assertFalse(self.fake.commands(DUMP_COMMAND))
                self.assertFalse(self.fake.commands("upgrade"))
                self.assertFalse(self.fake.commands("up"))

    def test_retry_takes_another_verified_backup_and_preserves_original_images(self):
        self.release.prepare()
        previous = self.release.previous_images_path.read_bytes()
        self.fake.busy_on_probe = 2
        with self.assertRaises(ReleaseError):
            self.release.activate()
        self.assertFalse(self.fake.commands("up"))
        first = json.loads(self.release.backups_path.read_text())["backups"][0]
        self.fake.busy_on_probe = 0
        self.release.activate()
        records = json.loads(self.release.backups_path.read_text())["backups"]
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0], first)
        self.assertNotEqual(records[0]["filename"], records[1]["filename"])
        self.assertEqual(len(self.fake.commands(DUMP_COMMAND)), 2)
        self.assertEqual(self.release.previous_images_path.read_bytes(), previous)
        self.assertEqual((self.release.directory / f"{REVISION}.env.backup").read_text(), self.original_env)

    def test_failed_fresh_backup_cannot_fall_back_to_an_older_backup(self):
        self.release.prepare()
        self.fake.busy_on_probe = 2
        with self.assertRaises(ReleaseError):
            self.release.activate()
        first = self.release.backups_path.read_bytes()
        self.fake.busy_on_probe = 0
        for failure in ("dump", "list", "decode", "copy"):
            with self.subTest(failure=failure):
                self.fake.backup_failure = failure
                with self.assertRaises(ReleaseError):
                    self.release.activate()
                self.assertEqual(self.release.backups_path.read_bytes(), first)
                self.assertEqual(len(self.fake.commands("upgrade")), 1)
                self.assertFalse(self.fake.commands("up"))

    def test_original_migration_release_still_requires_its_pre_0094_evidence(self):
        original = ReliabilityRelease(REVISION, self.root)
        self.assertEqual(original.previous_schema, PREVIOUS_SCHEMA)
        self.assertEqual(original.activated_services, ACTIVATED)
        self.assertEqual(original.directory.name, "reliability-release")
        self.assertEqual(self.release.directory.name, "notification-guard-release")
        self.assertNotEqual(original.backups_path, self.release.backups_path)
        self.assertEqual(original.lock_directory, self.release.lock_directory)
        original.prepare()
        with self.assertRaisesRegex(ReleaseError, "pre-migration backup evidence is missing"):
            original.activate()
        self.assertFalse(self.fake.commands(DUMP_COMMAND))
        self.assertFalse(self.fake.commands("up"))

    def test_success_retains_one_off_containers_and_temporary_postgres_archive(self):
        self.assertTrue(self.release.preserve_release_artifacts)
        self.release.prepare()
        self.release.activate()
        one_offs = self.fake.commands("run")
        self.assertEqual(len(one_offs), 3)
        self.assertTrue(all("--no-deps" in call and "--rm" not in call for call in one_offs))
        self.assertFalse(self.fake.commands("rm"))
        self.assertFalse(self.fake.commands("prune"))
        remote = self.fake.commands(DUMP_COMMAND)[0][-1]
        self.assertIn(remote, self.output.getvalue())
        self.assertEqual(len(list(self.release.directory.glob("*.pgdump"))), 1)
        self.assertFalse(list(self.release.directory.glob("*.partial")))

    def test_failed_copy_retains_partial_without_verified_backup_or_activation(self):
        self.release.prepare()
        self.fake.backup_failure = "copy"
        with self.assertRaisesRegex(ReleaseError, "checksum verification"):
            self.release.activate()
        partials = list(self.release.directory.glob(".*.pgdump.partial"))
        self.assertEqual(len(partials), 1)
        self.assertEqual(partials[0].read_bytes(), b"corrupt-copy")
        self.assertFalse(self.release.backups_path.exists())
        self.assertFalse(self.fake.commands("rm"))
        self.assertFalse(self.fake.commands("upgrade"))
        self.assertFalse(self.fake.commands("up"))
        self.assertEqual((self.root / ".env").read_text(), self.original_env)

    def test_failed_private_write_retention_is_opt_in_and_keeps_original_target(self):
        original = Release(REVISION, self.root)
        self.assertFalse(original.preserve_release_artifacts)
        for release in (self.release, original):
            with self.subTest(preserve=release.preserve_release_artifacts):
                release.directory.mkdir(parents=True, exist_ok=True)
                target = release.directory / "write-evidence.json"
                target.write_text("original")
                with (
                    patch("release_traveller_whatsapp.os.replace", side_effect=OSError("synthetic write failure")),
                    self.assertRaisesRegex(OSError, "synthetic write failure"),
                ):
                    release.write_private(target, "replacement")
                self.assertEqual(target.read_text(), "original")
                partials = list(release.directory.glob(".traveller-release-*"))
                self.assertEqual(len(partials), int(release.preserve_release_artifacts))
                if partials:
                    self.assertEqual(partials[0].read_text(), "replacement")

    def test_original_migration_release_keeps_default_archive_and_container_cleanup(self):
        original = ReliabilityRelease(REVISION, self.root)
        self.assertFalse(original.preserve_release_artifacts)
        self.fake.schema = PREVIOUS_SCHEMA
        original.prepare()
        original.activate()
        one_offs = self.fake.commands("run")
        self.assertEqual(len(one_offs), 3)
        self.assertTrue(all("--rm" in call for call in one_offs))
        cleanup = self.fake.commands("rm")
        self.assertEqual(len(cleanup), 1)
        self.assertEqual(cleanup[0][-4:], ["rm", "-f", "--", self.fake.commands(DUMP_COMMAND)[0][-1]])
        self.assertIn("backend, frontend, seven workers and beat.", self.output.getvalue())

    def test_failed_no_op_migration_retains_its_container_and_backup(self):
        self.release.prepare()
        self.fake.fail_migration = True
        with self.assertRaises(ReleaseError):
            self.release.activate()
        self.assertEqual(len(self.fake.commands("run")), 2)
        self.assertTrue(all("--rm" not in call for call in self.fake.commands("run")))
        self.assertFalse(self.fake.commands("rm"))
        self.assertFalse(self.fake.commands("up"))
        records = json.loads(self.release.backups_path.read_text())["backups"]
        self.assertEqual(len(records), 1)
        self.assertEqual((self.release.directory / records[0]["filename"]).read_bytes(), DUMP)
        self.assertNotIn("RELEASE VERIFIED", self.output.getvalue())

    def test_busy_workers_stop_before_backup_environment_or_code_change(self):
        self.release.prepare()
        self.fake.busy_on_probe = 1
        with self.assertRaisesRegex(ReleaseError, "busy"):
            self.release.activate()
        self.assertEqual((self.root / ".env").read_text(), self.original_env)
        self.assertFalse(self.fake.commands(DUMP_COMMAND))
        self.assertFalse(self.fake.commands("up"))

    def test_wrong_revision_and_retagged_images_fail_closed(self):
        self.fake.head = OLD_REVISION
        with self.assertRaisesRegex(ReleaseError, "Checkout does not match"):
            self.release.prepare()
        self.assertFalse(self.fake.commands("build"))
        self.fake.head = REVISION
        self.release.prepare()
        self.fake.images[self.fake.refs["backend"]]["Id"] = "sha256:" + "9" * 64
        with self.assertRaisesRegex(ReleaseError, "image tag changed"):
            self.release.activate()
        self.assertFalse(self.fake.commands(DUMP_COMMAND))
        self.assertFalse(self.fake.commands("up"))

    def test_unhealthy_public_site_cannot_report_verified(self):
        self.release.prepare()
        self.fake.public_status = "503"
        with self.assertRaisesRegex(ReleaseError, "did not return HTTP 200"):
            self.release.activate()
        self.assertNotIn("RELEASE VERIFIED", self.output.getvalue())

    def test_frontend_is_not_built_pinned_recovered_or_restarted(self):
        frontend_before = json.dumps(self.fake.containers["frontend"], sort_keys=True)
        self.release.prepare()
        build = self.fake.commands("build")
        self.assertEqual(len(build), 1)
        self.assertEqual(build[0][-2:], ["backend", "worker"])
        self.assertNotIn("frontend", build[0])
        manifest = json.loads(self.release.manifest_path.read_text())
        self.assertEqual(set(manifest["images"]), set(WORKERS) | {"backend"})
        self.assertNotIn("frontend", manifest["references"])
        previous = json.loads(self.release.previous_images_path.read_text())
        self.assertNotIn("frontend", previous["services"])
        self.release.activate()
        self.assertEqual(len(self.fake.commands("up")), 2)
        self.assertTrue(all("frontend" not in call for call in self.fake.commands("up")))
        self.assertEqual(
            set(json.loads(self.release.pin_path.read_text())["services"]),
            set(WORKERS) | {"backend"},
        )
        self.assertEqual(json.dumps(self.fake.containers["frontend"], sort_keys=True), frontend_before)
        self.assertIn(
            f"RELEASE VERIFIED: {REVISION}; schema {SCHEMA}; backend, seven workers and beat; frontend unchanged.",
            self.output.getvalue(),
        )
        self.assertFalse(any(
            set(call) & {"db", "redis", "nginx", "minio"}
            for call in self.fake.commands("up")
        ))

    def test_cli_requires_explicit_traffic_pause_before_activation(self):
        with (
            patch("sys.argv", ["release_notification_guard.py", "activate", "--revision", REVISION]),
            redirect_stderr(self.output),
        ):
            self.assertEqual(main(), 1)
        self.assertFalse(self.fake.calls)
        self.assertIn("--traffic-paused", self.output.getvalue())


if __name__ == "__main__":
    unittest.main()
