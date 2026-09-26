"""Stateful cutover sequencing tests; no live Docker or application data is used.

The actual MinIO/SeaweedFS copy, version pagination, metadata, tags, process
locking and uncertain-write behavior are exercised by qualify_storage_migration.
These tests focus on the release wrapper's process and volume decisions.
"""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

import test_release_current as current_tests
from release_reliability import DUMP_COMMAND
from release_traveller_whatsapp import ReleaseError
from test_release_current import (
    APP_STORAGE_ENV,
    LEGACY_STORAGE_ID,
    LEGACY_STORAGE_VOLUME,
    MAINTAINED_STORAGE_ID,
)


class StorageReleaseTests(unittest.TestCase):
    def setUp(self):
        current_tests.CurrentReleaseTests.setUp(self)

    def operations(self, verb, service):
        return [call for call in self.fake.calls if call[:2] == ["docker", "compose"]
                and self.fake.compose_command(call)[0][0] == verb
                and service in self.fake.compose_command(call)[0]]

    def writer_ids(self):
        return [self.fake.containers[name]["Id"] for name in (*self.release.workers, "backend")]

    def assert_legacy_and_writers_preserved(self, writers):
        self.assertEqual(self.fake.containers["minio"]["Image"], LEGACY_STORAGE_ID)
        self.assertEqual(self.fake.containers["minio"]["Mounts"][0]["Name"], LEGACY_STORAGE_VOLUME)
        self.assertIn(LEGACY_STORAGE_VOLUME, self.fake.volumes)
        self.assertTrue(all(self.fake.containers[name]["State"]["Running"] for name in (*self.release.workers, "backend")))
        self.assertEqual(self.fake.commands("start")[-1], ["docker", "start", *writers])
        self.assertFalse(self.operations("up", "minio"))
        self.assertFalse(self.fake.commands("upgrade"))
        self.assertFalse(any(set(call) & {"down", "prune", "purge", "volume", "--volumes"} for call in self.fake.calls))

    def test_prepare_preserves_running_provider_and_allocates_a_separate_target(self):
        original_provider = copy.deepcopy(self.fake.containers["minio"])
        self.release.prepare()
        values = self.fake.environment()
        self.assertNotEqual(values["OBJECT_STORAGE_DATA_VOLUME"], LEGACY_STORAGE_VOLUME)
        self.assertEqual(self.fake.containers["minio"], original_provider)
        self.assertFalse(self.fake.commands("stop"))
        self.assertFalse(self.fake.commands("up"))
        self.assertEqual(self.fake.volumes, {LEGACY_STORAGE_VOLUME})
        self.assertTrue(Path(values["OBJECT_STORAGE_IDENTITY_FILE"]).is_file())
        self.assertFalse(Path(values["OBJECT_STORAGE_CUTOVER_PROOF"]).exists())
        self.assertTrue(all(values[key] == value for key, value in APP_STORAGE_ENV.items()))

    def test_backup_then_provision_then_fence_copy_stage_stop_and_provider_cutover(self):
        writers = self.writer_ids()
        self.release.prepare()
        self.release.activate()
        calls = self.fake.calls
        sequence = [
            self.fake.commands(DUMP_COMMAND)[0],
            self.fake.commands("scripts/provision_database_roles.py")[0],
            self.operations("stop", "backend")[0],
            self.operations("up", "storage-stage")[0],
            self.operations("run", "storage-copy")[0],
            self.operations("stop", "storage-stage")[0],
            self.operations("up", "minio")[0],
            self.fake.commands("start")[0],
            self.fake.commands("upgrade")[0],
        ]
        self.assertEqual([calls.index(call) for call in sequence], sorted(calls.index(call) for call in sequence))
        self.assertEqual(self.fake.commands("start")[0], ["docker", "start", *writers])
        self.assertFalse(self.fake.containers["storage-stage"]["State"]["Running"])
        self.assertEqual(self.fake.containers["minio"]["Image"], MAINTAINED_STORAGE_ID)
        values = self.fake.environment()
        self.assertEqual(self.fake.containers["minio"]["Mounts"][0]["Name"], values["OBJECT_STORAGE_DATA_VOLUME"])
        self.assertIn(LEGACY_STORAGE_VOLUME, self.fake.volumes)
        proof = json.loads(Path(values["OBJECT_STORAGE_CUTOVER_PROOF"]).read_text())
        self.assertEqual(proof["source_volume"], LEGACY_STORAGE_VOLUME)
        self.assertEqual(proof["target_volume"], values["OBJECT_STORAGE_DATA_VOLUME"])
        self.assertEqual(proof["identity_sha256"], hashlib.sha256(Path(values["OBJECT_STORAGE_IDENTITY_FILE"]).read_bytes()).hexdigest())
        self.assertFalse(proof["source_deleted"])
        self.assertFalse(any(set(call) & {"down", "prune", "purge", "volume", "--volumes"} for call in calls))

    def test_source_bucket_endpoint_and_credentials_mismatch_stop_before_fencing(self):
        self.release.prepare()
        for field in APP_STORAGE_ENV:
            with self.subTest(field=field):
                config = self.fake.config()
                config["services"]["backend"]["environment"][field] = "unexpected-target"
                with self.assertRaisesRegex(ReleaseError, "cannot change the live bucket"):
                    self.release.storage.validate(config)
        self.assertFalse(self.fake.commands("stop"))
        self.assertFalse(self.fake.commands("up"))

    def test_source_admin_and_volume_mismatch_stop_before_fencing(self):
        self.release.prepare()
        for field in ("MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD", "OBJECT_STORAGE_DATA_VOLUME"):
            with self.subTest(field=field):
                config = self.fake.config()
                config["services"]["database-admin"]["environment"][field] = (
                    LEGACY_STORAGE_VOLUME if field == "OBJECT_STORAGE_DATA_VOLUME" else "wrong-source-credential"
                )
                with self.assertRaises(ReleaseError):
                    self.release.storage.validate(config)
        self.assertFalse(self.fake.commands("stop"))

    def test_storage_service_network_and_live_network_must_match(self):
        self.release.prepare()
        for service in ("backend", "minio", "storage-stage", "storage-copy"):
            with self.subTest(service=service):
                config = self.fake.config()
                config["services"][service]["networks"] = {"other-network": None}
                with self.assertRaisesRegex(ReleaseError, "verified application network"):
                    self.release.storage.validate(config)
        source = self.fake.containers["minio"]
        source["NetworkSettings"]["Networks"] = {}
        with self.assertRaises(ReleaseError):
            self.release.storage.validate(self.fake.config())
        self.assertFalse(self.fake.commands("stop"))

    def test_identity_tamper_stops_activation_before_backup_or_fencing(self):
        self.release.prepare()
        identity = Path(self.fake.environment()["OBJECT_STORAGE_IDENTITY_FILE"])
        original = identity.read_text()
        identity.write_text(original.replace("existing-app", "other-app"))
        with self.assertRaises(ReleaseError):
            self.release.activate()
        self.assertFalse(self.fake.commands(DUMP_COMMAND))
        self.assertFalse(self.fake.commands("scripts/provision_database_roles.py"))
        self.assertFalse(self.fake.commands("stop"))

    def test_prepared_target_volume_and_readonly_identity_mount_are_required(self):
        self.release.prepare()
        config = self.fake.config()
        config["volumes"]["object_storage_data"]["name"] = LEGACY_STORAGE_VOLUME
        with self.assertRaisesRegex(ReleaseError, "Rendered storage volume differs"):
            self.release.storage.validate(config)
        for service in ("minio", "storage-stage"):
            for invalid in ("data", "identity-source", "identity-writable"):
                with self.subTest(service=service, invalid=invalid):
                    config = self.fake.config()
                    mounts = config["services"][service]["volumes"]
                    if invalid == "data":
                        mounts[0]["source"] = "legacy-data-volume"
                    elif invalid == "identity-source":
                        mounts[1]["source"] = "unverified-identity.json"
                    else:
                        mounts[1]["read_only"] = False
                    with self.assertRaises(ReleaseError):
                        self.release.storage.validate(config)
        self.assertFalse(self.fake.commands("stop"))

    def test_unrecognized_source_provider_or_mount_cannot_prepare(self):
        original = copy.deepcopy(self.fake.containers["minio"])
        for invalid in ("provider", "bind-mount"):
            with self.subTest(invalid=invalid):
                self.fake.containers["minio"] = copy.deepcopy(original)
                if invalid == "provider":
                    self.fake.containers["minio"]["Config"]["Image"] = "unreviewed/provider:latest"
                else:
                    self.fake.containers["minio"]["Mounts"][0]["Type"] = "bind"
                with self.assertRaises(ReleaseError):
                    self.release.prepare()
                self.assertEqual((self.root / ".env").read_text(), self.original)
                self.assertFalse(self.fake.commands("stop"))
                self.assertFalse(self.fake.commands("up"))

    def test_copy_failure_restarts_exact_old_processes_and_preserves_both_volumes(self):
        writers = self.writer_ids()
        self.release.prepare()
        self.fake.fail_copy = True
        with self.assertRaises(ReleaseError):
            self.release.activate()
        self.assert_legacy_and_writers_preserved(writers)
        values = self.fake.environment()
        self.assertIn(values["OBJECT_STORAGE_DATA_VOLUME"], self.fake.volumes)
        self.assertFalse(Path(values["OBJECT_STORAGE_CUTOVER_PROOF"]).exists())

    def test_copy_timeout_stops_surviving_container_before_restoring_old_processes(self):
        writers = self.writer_ids()
        self.release.prepare()
        self.fake.copy_timeout = True
        with self.assertRaisesRegex(ReleaseError, "TimeoutExpired"):
            self.release.activate()
        self.assert_legacy_and_writers_preserved(writers)
        self.assertFalse(self.fake.containers["storage-copy"]["State"]["Running"])
        stop = next(call for call in self.fake.calls if call[:2] == ["docker", "stop"])
        restart = self.fake.commands("start")[-1]
        self.assertLess(self.fake.calls.index(stop), self.fake.calls.index(restart))
        first_target = self.fake.environment()["OBJECT_STORAGE_DATA_VOLUME"]
        self.release.prepare()
        self.assertNotEqual(self.fake.environment()["OBJECT_STORAGE_DATA_VOLUME"], first_target)
        self.assertIn(first_target, self.fake.volumes)

    def test_copy_that_cannot_stop_keeps_old_writers_fenced_and_blocks_prepare(self):
        self.release.prepare()
        self.fake.copy_timeout = self.fake.copy_stop_failure = True
        with self.assertRaisesRegex(ReleaseError, "writer recovery stopped"):
            self.release.activate()
        self.assertFalse(self.fake.commands("start"))
        self.assertFalse(self.operations("up", "minio"))
        self.assertTrue(self.fake.containers["storage-copy"]["State"]["Running"])
        old_environment = (self.root / ".env").read_text()
        with self.assertRaisesRegex(ReleaseError, "writer recovery stopped"):
            self.release.prepare()
        self.assertEqual((self.root / ".env").read_text(), old_environment)
        self.assertFalse(self.fake.commands("start"))

    def test_unverified_copy_report_never_replaces_provider(self):
        writers = self.writer_ids()
        self.release.prepare()
        self.fake.copy_report["source_deleted"] = True
        with self.assertRaisesRegex(ReleaseError, "verified preservation evidence"):
            self.release.activate()
        self.assert_legacy_and_writers_preserved(writers)

    def test_unclean_writer_prevents_stage_and_copy_then_restarts_original_processes(self):
        writers = self.writer_ids()
        self.release.prepare()
        self.fake.unclean_writer = "backend"
        with self.assertRaisesRegex(ReleaseError, "did not stop cleanly"):
            self.release.activate()
        self.assertFalse(self.operations("up", "storage-stage"))
        self.assertFalse(self.operations("run", "storage-copy"))
        self.assert_legacy_and_writers_preserved(writers)

    def test_unclean_stage_never_replaces_provider_and_restores_original_processes(self):
        writers = self.writer_ids()
        self.release.prepare()
        self.fake.unclean_writer = "storage-stage"
        with self.assertRaisesRegex(ReleaseError, "Staging did not stop cleanly"):
            self.release.activate()
        self.assertTrue(self.operations("run", "storage-copy"))
        self.assert_legacy_and_writers_preserved(writers)

    def test_stage_start_failure_restarts_original_processes_without_copy(self):
        writers = self.writer_ids()
        self.release.prepare()
        self.fake.fail_stage = True
        with self.assertRaises(ReleaseError):
            self.release.activate()
        self.assertFalse(self.operations("run", "storage-copy"))
        self.assert_legacy_and_writers_preserved(writers)

    def test_unreadable_capacity_prevents_copy_and_restores_original_processes(self):
        writers = self.writer_ids()
        self.release.prepare()
        self.fake.storage_space = "unparseable disk capacity"
        with self.assertRaisesRegex(ReleaseError, "Could not measure"):
            self.release.activate()
        self.assertFalse(self.operations("run", "storage-copy"))
        self.assert_legacy_and_writers_preserved(writers)

    def test_prepare_after_uncertain_copy_uses_a_fresh_isolated_target(self):
        self.release.prepare()
        first = self.fake.environment()
        self.fake.fail_copy = True
        with self.assertRaises(ReleaseError):
            self.release.activate()
        self.release.prepare()
        second = self.fake.environment()
        for key in ("OBJECT_STORAGE_DATA_VOLUME", "OBJECT_STORAGE_MIGRATION_DIRECTORY", "OBJECT_STORAGE_CUTOVER_PROOF"):
            self.assertNotEqual(first[key], second[key])
        self.assertIn(first["OBJECT_STORAGE_DATA_VOLUME"], self.fake.volumes)
        self.assertIn(LEGACY_STORAGE_VOLUME, self.fake.volumes)
        self.assertNotIn(second["OBJECT_STORAGE_DATA_VOLUME"], self.fake.volumes)
        self.assertTrue(Path(first["OBJECT_STORAGE_IDENTITY_FILE"]).is_file())
        self.assertTrue(Path(second["OBJECT_STORAGE_IDENTITY_FILE"]).is_file())

    def test_maintained_provider_requires_matching_proof_and_does_not_copy_again(self):
        self.release.prepare()
        self.release.activate()
        values = self.fake.environment()
        copies = len(self.operations("run", "storage-copy"))
        self.release.prepare()
        self.assertEqual(self.fake.environment()["OBJECT_STORAGE_DATA_VOLUME"], values["OBJECT_STORAGE_DATA_VOLUME"])
        self.assertEqual(len(self.operations("run", "storage-copy")), copies)
        proof_path = Path(values["OBJECT_STORAGE_CUTOVER_PROOF"])
        original = proof_path.read_text()
        for field in ("target_volume", "bucket", "identity_sha256"):
            proof = json.loads(original)
            proof[field] = "incorrect-proof"
            proof_path.write_text(json.dumps(proof))
            with self.assertRaisesRegex(ReleaseError, "cutover evidence does not match"):
                self.release.storage.validate(self.fake.config())
        proof_path.write_text(original)

    def test_active_maintained_provider_requires_exact_readonly_identity_mount(self):
        self.release.prepare()
        self.release.activate()
        original = copy.deepcopy(self.fake.containers["minio"]["Mounts"])
        for invalid in ("source", "writable", "missing"):
            with self.subTest(invalid=invalid):
                mounts = copy.deepcopy(original)
                if invalid == "source":
                    mounts[1]["Source"] = "unverified-identity.json"
                elif invalid == "writable":
                    mounts[1]["RW"] = True
                else:
                    mounts.pop()
                self.fake.containers["minio"]["Mounts"] = mounts
                with self.assertRaisesRegex(ReleaseError, "active provider identity mount differs"):
                    self.release.storage.validate(self.fake.config())


if __name__ == "__main__":
    unittest.main()
