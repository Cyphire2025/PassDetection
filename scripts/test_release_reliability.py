"""Offline recovery/activation contracts; Docker and PostgreSQL are never called."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from release_reliability import (
    DUMP_COMMAND,
    PREVIOUS_SCHEMA,
    SCHEMA,
    ReliabilityRelease,
)
from release_traveller_whatsapp import (
    ACTIVATED,
    Release,
    ReleaseError,
    updated_environment,
)
from test_release_traveller_whatsapp import OLD_IMAGE, REVISION, FakeDocker

DUMP = b"PGDMP\x01synthetic-custom-archive-for-offline-tests-only"
DATABASE_ENV = {
    "POSTGRES_DB": "application", "POSTGRES_USER": "application",
    "POSTGRES_PASSWORD": "private-database-password",
}


class RecoveryDocker(FakeDocker):
    def __init__(self, root):
        super().__init__(root)
        self.expected_schema = SCHEMA
        self.schema = PREVIOUS_SCHEMA
        self.images[OLD_IMAGE] = {"Id": OLD_IMAGE, "Config": {"Env": []}}
        self.containers["db"] = self.make_container("db")
        self.containers["db"]["Config"]["Env"].extend(
            f"{key}={value}" for key, value in DATABASE_ENV.items()
        )
        self.backup_failure = None

    def config(self):
        result = super().config()
        result["services"]["db"] = {"image": "postgres:known", "environment": dict(DATABASE_ENV)}
        result["services"]["backend"]["environment"].update(DATABASE_ENV, POSTGRES_HOST="db")
        return result

    def run(self, args, **kwargs):
        args = list(args)
        handled = False
        code, output = 0, ""
        if args[:3] == ["docker", "image", "ls"]:
            handled = True
            output = self.images.get(args[-1], {}).get("Id", "")
        elif args[:3] == ["docker", "image", "tag"]:
            handled = True
            self.images[args[-1]] = copy.deepcopy(self.images[args[-2]])
        elif args[:2] == ["docker", "cp"]:
            handled = True
            Path(args[-1]).write_bytes(b"corrupt-copy" if self.backup_failure == "copy" else DUMP)
        elif args[:2] == ["docker", "compose"] and "db" in args and "exec" in args:
            handled = True
            if DUMP_COMMAND in args:
                code = int(self.backup_failure == "dump")
            elif "pg_restore" in args:
                if "--list" in args:
                    output = "TABLE DATA public alembic_version" if self.backup_failure != "list" else "not-the-application"
                else:
                    self.assert_full_decode = "--file=/dev/null" in args
                    code = int(self.backup_failure == "decode")
            elif "sha256sum" in args:
                output = hashlib.sha256(DUMP).hexdigest() + "  " + args[-1]
            elif "rm" in args:
                assert args[-1].startswith("/tmp/passdetection-reliability-")
                assert "--" in args
            else:
                raise AssertionError(args)
        if not handled:
            return super().run(args, **kwargs)
        self.calls.append(args)
        return subprocess.CompletedProcess(args, code, stdout=output, stderr="private diagnostic")


class ReliabilityReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.original_env = f"PASSWORD=private-test-value\nEXPECTED_DATABASE_SCHEMA_REVISION={PREVIOUS_SCHEMA}\n"
        (self.root / ".env").write_text(self.original_env)
        self.fake = RecoveryDocker(self.root)
        patcher = patch("release_traveller_whatsapp.subprocess.run", side_effect=self.fake.run)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.output = io.StringIO()
        redirector = redirect_stdout(self.output)
        redirector.__enter__()
        self.addCleanup(redirector.__exit__, None, None, None)
        self.release = ReliabilityRelease(REVISION, self.root)

    def test_prepare_keeps_previous_image_ids_with_tags_before_any_build(self):
        self.release.prepare()
        preserved = json.loads(self.release.previous_images_path.read_text())
        self.assertEqual(set(preserved["services"]), set(ACTIVATED))
        self.assertFalse(preserved["automatic_rollback_allowed"])
        self.assertTrue(all(item["image_id"] == OLD_IMAGE for item in preserved["services"].values()))
        self.assertLess(self.fake.calls.index(self.fake.commands("tag")[-1]), self.fake.calls.index(self.fake.commands("build")[0]))
        self.assertFalse(self.fake.commands(DUMP_COMMAND))
        self.assertFalse(self.fake.commands("up"))
        first = self.release.previous_images_path.read_bytes()
        self.release.prepare()
        self.assertEqual(self.release.previous_images_path.read_bytes(), first)

    def test_activate_validates_archive_and_checksum_before_environment_and_migration(self):
        self.release.prepare()
        self.release.activate()
        backups = json.loads(self.release.backups_path.read_text())["backups"]
        self.assertEqual(len(backups), 1)
        record = backups[0]
        self.assertEqual((self.release.directory / record["filename"]).read_bytes(), DUMP)
        self.assertEqual(record["schema"], PREVIOUS_SCHEMA)
        self.assertEqual(record["sha256"], hashlib.sha256(DUMP).hexdigest())
        self.assertEqual(record["bytes"], len(DUMP))
        self.assertFalse(record["restore_rehearsed"])
        self.assertTrue(self.fake.assert_full_decode)
        self.assertEqual(self.fake.schema, SCHEMA)
        self.assertLess(self.fake.calls.index(self.fake.commands("cp")[0]), self.fake.calls.index(self.fake.commands("upgrade")[0]))
        self.assertEqual((self.release.directory / f"{REVISION}.env.backup").read_text(), self.original_env)
        self.assertIn("BACKUP VERIFIED", self.output.getvalue())
        self.assertIn("RELEASE VERIFIED", self.output.getvalue())
        self.assertNotIn("private-test-value", self.output.getvalue())
        self.assertFalse(any(set(call) & {"downgrade", "down", "kill", "purge", "reset", "stash"} for call in self.fake.calls))

    def test_backup_failures_leave_environment_schema_and_containers_unchanged(self):
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

    def test_activation_retry_preserves_pre_migration_backup_and_never_auto_rolls_back(self):
        self.release.prepare()
        self.fake.busy_on_probe = 2
        with self.assertRaises(ReleaseError):
            self.release.activate()
        before = self.release.backups_path.read_bytes()
        self.fake.busy_on_probe = 0
        self.release.activate()
        self.assertEqual(self.release.backups_path.read_bytes(), before)
        self.assertEqual(len(self.fake.commands(DUMP_COMMAND)), 1)
        self.assertFalse(self.fake.commands("downgrade"))

    def test_corrupt_preserved_archive_blocks_retry_after_migration(self):
        self.release.prepare()
        self.fake.busy_on_probe = 2
        with self.assertRaises(ReleaseError):
            self.release.activate()
        backup = json.loads(self.release.backups_path.read_text())["backups"][0]
        (self.release.directory / backup["filename"]).write_bytes(b"corrupted")
        self.fake.busy_on_probe = 0
        with self.assertRaisesRegex(ReleaseError, "integrity validation"):
            self.release.activate()
        self.assertFalse(self.fake.commands("up"))

    def test_missing_pre_migration_evidence_cannot_be_replaced_by_post_migration_dump(self):
        self.release.prepare()
        self.fake.schema = SCHEMA
        with self.assertRaisesRegex(ReleaseError, "pre-migration backup evidence is missing"):
            self.release.activate()
        self.assertFalse(self.fake.commands(DUMP_COMMAND))
        self.assertFalse(self.fake.commands("up"))

    def test_retagged_previous_image_blocks_activation_before_backup(self):
        self.release.prepare()
        previous = json.loads(self.release.previous_images_path.read_text())["services"]
        self.fake.images[previous["backend"]["tag"]]["Id"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(ReleaseError, "recovery tag changed"):
            self.release.activate()
        self.assertFalse(self.fake.commands(DUMP_COMMAND))
        self.assertFalse(self.fake.commands("upgrade"))

    def test_shared_base_defaults_and_schema_directory_guards(self):
        legacy = Release(REVISION, self.root)
        self.assertEqual(legacy.expected_schema, "0093_phone_welcome")
        self.assertEqual(legacy.previous_schema, "0092_whatsapp_matching_fields")
        self.assertEqual(legacy.directory.name, "traveller-whatsapp-release")
        self.assertEqual(legacy.lock_directory, self.release.lock_directory)
        self.assertIn(SCHEMA, updated_environment(self.original_env, REVISION, SCHEMA))
        with self.assertRaises(ReleaseError):
            Release(REVISION, self.root, directory_name="../../other")
        with self.assertRaises(ReleaseError):
            Release(REVISION, self.root, expected_schema="head; echo unsafe")

    def test_backup_target_mismatch_stops_before_any_database_or_environment_change(self):
        self.release.prepare()
        self.fake.containers["db"]["Config"]["Env"].append("POSTGRES_DB=another-database")
        with self.assertRaisesRegex(ReleaseError, "database identity/settings"):
            self.release.activate()
        self.assertEqual((self.root / ".env").read_text(), self.original_env)
        self.assertFalse(self.fake.commands(DUMP_COMMAND))
        self.assertFalse(self.fake.commands("upgrade"))

    def test_prepare_rejects_an_external_database_target(self):
        original_config = self.fake.config

        def external_config():
            result = original_config()
            result["services"]["backend"]["environment"]["POSTGRES_HOST"] = "another-host"
            return result

        self.fake.config = external_config
        with self.assertRaisesRegex(ReleaseError, "existing db PostgreSQL service"):
            self.release.prepare()
        self.assertFalse(self.fake.commands("build"))


if __name__ == "__main__":
    unittest.main()
