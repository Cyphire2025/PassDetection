"""Crash-boundary recovery uses real private files and simulated Docker identities."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from release_traveller_whatsapp import PROJECT_LABEL, SERVICE_LABEL, ReleaseError
from storage_writer_fence import StorageWriterFence, recover_pending_storage_writers


class FenceDocker:
    def __init__(self, root):
        self.root = root
        self.directory = root / "tmp/current-release"
        self.revision = "a" * 40
        self.workers = ("worker", "email-beat")
        self.compose = ["docker", "compose", "-p", "synthetic-project"]
        self.calls = []
        self.fail_reload = False
        self.fail_start_after = None
        self.fail_copy_stop = False
        self.copy_survives_stop = False
        self.copy_auto_remove = False
        self.containers = {name: self.make(name) for name in (*self.workers, "backend", "nginx", "minio")}
        self.containers["minio"]["Mounts"] = [{"Type": "volume", "Name": "original-volume", "Destination": "/data"}]
        private = self.directory / "storage/attempt"
        private.mkdir(parents=True)
        self.identity_path = private / "identities.json"
        self.identity_path.write_text('{"synthetic_secret":"must-not-enter-checkpoint"}')
        self.proof_path = private / "cutover.json"
        self.config = {"services": {"database-admin": {"environment": {
            "OBJECT_STORAGE_IDENTITY_FILE": str(self.identity_path),
            "OBJECT_STORAGE_CUTOVER_PROOF": str(self.proof_path),
            "OBJECT_STORAGE_DATA_VOLUME": "verified-target-volume",
            "S3_BUCKET_NAME": "synthetic-passports",
        }}, "storage-copy": {"environment": {
            "S3_BUCKET_NAME": "synthetic-passports", "STORAGE_SOURCE_ENDPOINT": "http://minio:9000",
            "STORAGE_DESTINATION_ENDPOINT": "http://storage-stage:9000",
        }}}}

    def make(self, service, *, identifier=None, image=None):
        return {"Id": identifier or service + "-original-id", "Image": image or service + "-original-image",
                "Config": {"Labels": {PROJECT_LABEL: "synthetic-project", SERVICE_LABEL: service,
                           "com.docker.compose.project.working_dir": str(self.root)}},
                "HostConfig": {"ExtraHosts": []},
                "NetworkSettings": {"Networks": {"synthetic-net": {
                    "NetworkID": "synthetic-network-id", "Aliases": [service],
                }}},
                "State": {"Running": True, "ExitCode": 0, "Health": {"Status": "healthy"}}, "Mounts": []}

    def container(self, service):
        return copy.deepcopy(self.containers[service])

    def inspect(self, identifier):
        for value in self.containers.values():
            if value["Id"] == identifier:
                return copy.deepcopy(value)
        raise ReleaseError("Recorded container no longer exists")

    def write_private(self, path, document):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document)
        self.calls.append(("checkpoint", json.loads(document)["phase"]))

    def run(self, *args, **kwargs):
        self.calls.append(args)
        if args[:4] == ("docker", "ps", "--all", "--quiet"):
            name_filter = next((item for item in args if item.startswith("name=^/")), None)
            if name_filter:
                return "\n".join(item["Id"] for item in self.containers.values()
                                 if item.get("Name") == name_filter[len("name=^"):-1])
            project = next(item.split("=", 2)[-1] for item in args if item.startswith("label=" + PROJECT_LABEL))
            service = next(item.split("=", 2)[-1] for item in args if item.startswith("label=" + SERVICE_LABEL))
            return "\n".join(item["Id"] for item in self.containers.values()
                             if item["Config"]["Labels"].get(PROJECT_LABEL) == project
                             and item["Config"]["Labels"].get(SERVICE_LABEL) == service)
        if args[:2] == ("docker", "stop"):
            if self.fail_copy_stop:
                raise ReleaseError("Injected copy stop failure")
            item = next(item for item in self.containers.values() if item["Id"] == args[-1])
            if not self.copy_survives_stop:
                item["State"]["Running"] = False
            if self.copy_auto_remove:
                del self.containers["storage-copy"]
            return ""
        if args[:2] == ("docker", "start"):
            for index, identifier in enumerate(args[2:]):
                if self.fail_start_after == index:
                    raise ReleaseError("Injected partial Docker start failure")
                item = next(item for item in self.containers.values() if item["Id"] == identifier)
                item["State"]["Running"] = True
            return ""
        if args[:2] == ("docker", "exec") and args[3:] in (("nginx", "-t"), ("nginx", "-s", "reload")):
            if self.fail_reload and args[-1] == "reload":
                raise ReleaseError("Injected nginx reload failure")
            return ""
        raise AssertionError(f"Unexpected operation: {args}")


class StorageWriterFenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.release = FenceDocker(Path(temporary.name))
        self.fence = StorageWriterFence(self.release)

    def begin(self):
        self.fence.begin(self.release.container("minio"),
                         [self.release.container(name) for name in (*self.release.workers, "backend")],
                         self.release.config, "maintained-provider-image", "prepared-copy-image")

    def running_copy(self):
        claim = json.loads(self.fence.path.read_text())["copy"]
        container = self.release.make("storage-copy", image=claim["image"])
        container["Name"] = "/" + claim["name"]
        container["Config"].update(Cmd=["python", "scripts/copy_storage_snapshot.py"],
                                   Env=[f"{key}={value}" for key, value in claim["environment"].items()])
        container["Config"]["Labels"]["passdetection.storage-copy-token"] = claim["token"]
        container["Mounts"] = [{"Type": "bind", "Source": claim["evidence_directory"], "Destination": "/evidence"}]
        self.release.containers["storage-copy"] = container
        return container

    def stop_writers(self):
        for name in (*self.release.workers, "backend"):
            self.release.containers[name]["State"]["Running"] = False

    def proof(self):
        self.release.proof_path.write_text(json.dumps({
            "source_volume": "original-volume", "target_volume": "verified-target-volume",
            "bucket": "synthetic-passports",
            "identity_sha256": hashlib.sha256(self.release.identity_path.read_bytes()).hexdigest(),
            "every_copied_body_sha256_verified": True, "source_deleted": False,
        }))
        self.fence.verified_target()

    def switch_target(self):
        self.fence.begin_handoff()
        target = self.release.make("minio", identifier="new-provider-id", image="maintained-provider-image")
        target["Mounts"] = [
            {"Type": "volume", "Name": "verified-target-volume", "Destination": "/data"},
            {"Source": str(self.release.identity_path), "Destination": "/run/secrets/s3.json", "RW": False},
        ]
        self.release.containers["minio"] = target

    def assert_no_starts(self):
        self.assertFalse(any(call[:2] == ("docker", "start") for call in self.release.calls))

    def test_checkpoint_exists_before_fencing_and_contains_no_credentials(self):
        self.begin()
        record = json.loads(self.fence.path.read_text())
        self.assertEqual(record["phase"], "fencing")
        self.assertEqual(record["source"]["volume"], "original-volume")
        self.assertEqual(record["target"]["volume"], "verified-target-volume")
        self.assertEqual({item["service"] for item in record["writers"]}, {"worker", "email-beat", "backend"})
        self.assertTrue(all(item["id"] and item["image"] and item["working_directory"] for item in record["writers"]))
        self.assertNotIn("must-not-enter-checkpoint", self.fence.path.read_text())
        self.assertTrue(all(item["State"]["Running"] for item in self.release.containers.values()))

    def test_no_checkpoint_is_a_noop(self):
        recover_pending_storage_writers(self.release)
        self.assertEqual(self.release.calls, [])

    def test_killed_helper_recovery_stops_verified_copy_before_restarting_writers(self):
        self.begin()
        self.stop_writers()
        copy_job = self.running_copy()
        self.release.compose = []
        recover_pending_storage_writers(self.release)
        self.assertFalse(copy_job["State"]["Running"])
        stop = ("docker", "stop", "--time", "30", copy_job["Id"])
        restart = next(call for call in self.release.calls if call[:2] == ("docker", "start"))
        self.assertLess(self.release.calls.index(stop), self.release.calls.index(restart))
        self.assertEqual(json.loads(self.fence.path.read_text())["phase"], "complete")
        self.assertFalse(any(set(call) & {"rm", "down", "prune"} for call in self.release.calls))

    def test_auto_removed_copy_after_stop_allows_safe_recovery(self):
        self.begin()
        self.stop_writers()
        self.running_copy()
        self.release.copy_auto_remove = True
        self.fence.restore()
        self.assertNotIn("storage-copy", self.release.containers)
        self.assertEqual(json.loads(self.fence.path.read_text())["phase"], "complete")

    def test_foreign_same_name_or_changed_copy_configuration_is_never_stopped(self):
        self.begin()
        self.stop_writers()
        original = copy.deepcopy(self.running_copy())
        for changed in ("image", "project", "token", "command", "endpoint", "evidence"):
            with self.subTest(changed=changed):
                job = copy.deepcopy(original)
                if changed == "image":
                    job["Image"] = "foreign-image"
                elif changed == "project":
                    job["Config"]["Labels"][PROJECT_LABEL] = "foreign-project"
                elif changed == "token":
                    job["Config"]["Labels"]["passdetection.storage-copy-token"] = "foreign-token"
                elif changed == "command":
                    job["Config"]["Cmd"] = ["unrelated-task"]
                elif changed == "endpoint":
                    job["Config"]["Env"] = ["STORAGE_DESTINATION_ENDPOINT=http://other-store:9000"]
                else:
                    job["Mounts"][0]["Source"] = "other-copy-directory"
                self.release.containers["storage-copy"] = job
                with self.assertRaises(ReleaseError):
                    self.fence.restore()
                self.assert_no_starts()
                self.assertFalse(any(call[:2] == ("docker", "stop") for call in self.release.calls))

    def test_failed_copy_stop_keeps_writers_fenced_and_checkpoint_pending(self):
        self.begin()
        self.stop_writers()
        self.running_copy()
        self.release.fail_copy_stop = True
        with self.assertRaisesRegex(ReleaseError, "copy stop failure"):
            self.fence.restore()
        self.assert_no_starts()
        self.assertEqual(json.loads(self.fence.path.read_text())["phase"], "fencing")

    def test_successful_stop_command_is_not_enough_if_copy_still_runs(self):
        self.begin()
        self.stop_writers()
        self.running_copy()
        self.release.copy_survives_stop = True
        with self.assertRaisesRegex(ReleaseError, "still running"):
            self.fence.restore()
        self.assert_no_starts()

    def test_missing_copy_claim_cannot_be_treated_as_completed(self):
        self.begin()
        self.stop_writers()
        record = json.loads(self.fence.path.read_text())
        del record["copy"]
        self.fence.path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ReleaseError, "claim is missing"):
            self.fence.restore()
        self.assert_no_starts()

    def test_new_process_recovers_after_crash_with_backend_stopped(self):
        self.begin()
        self.stop_writers()
        self.release.compose = []  # Normal running-backend preflight has not run.
        recover_pending_storage_writers(self.release)
        record = json.loads(self.fence.path.read_text())
        self.assertEqual((record["phase"], record["restored_against"]), ("complete", "original_source"))
        self.assertTrue(all(item["State"]["Running"] for item in self.release.containers.values()))
        calls = self.release.calls
        self.assertLess(calls.index(("docker", "exec", "nginx-original-id", "nginx", "-t")),
                        calls.index(("docker", "exec", "nginx-original-id", "nginx", "-s", "reload")))
        self.assertEqual(calls[-1], ("checkpoint", "complete"))

    def test_partial_fence_starts_only_stopped_original_process(self):
        self.begin()
        self.release.containers["worker"]["State"]["Running"] = False
        self.fence.restore()
        starts = [call for call in self.release.calls if call[:2] == ("docker", "start")]
        self.assertEqual(starts, [("docker", "start", "worker-original-id")])

    def test_verified_copy_before_handoff_can_return_to_still_authoritative_source(self):
        self.begin()
        self.stop_writers()
        self.proof()
        self.fence.restore()
        self.assertEqual(json.loads(self.fence.path.read_text())["restored_against"], "original_source")

    def test_verified_target_is_used_without_source_rollback(self):
        self.begin()
        self.stop_writers()
        self.proof()
        self.switch_target()
        target_before = copy.deepcopy(self.release.containers["minio"])
        recover_pending_storage_writers(self.release)
        self.assertEqual(self.release.containers["minio"], target_before)
        self.assertEqual(json.loads(self.fence.path.read_text())["restored_against"], "verified_target")
        self.assertFalse(any(set(call) & {"rm", "down", "prune", "up", "stop"} for call in self.release.calls))

    def test_handoff_started_but_source_remains_is_ambiguous(self):
        self.begin()
        self.stop_writers()
        self.proof()
        self.fence.begin_handoff()
        with self.assertRaisesRegex(ReleaseError, "incomplete or ambiguous"):
            self.fence.restore()
        self.assert_no_starts()

    def test_unknown_provider_image_volume_or_identity_mount_never_restarts_writers(self):
        self.begin()
        self.stop_writers()
        self.proof()
        self.switch_target()
        valid = copy.deepcopy(self.release.containers["minio"])
        for field in ("image", "volume", "identity", "identity-writeable", "health", "stopped"):
            with self.subTest(field=field):
                current = copy.deepcopy(valid)
                if field == "image":
                    current["Image"] = "unreviewed-image"
                elif field == "volume":
                    current["Mounts"][0]["Name"] = "empty-unverified-volume"
                elif field == "identity":
                    current["Mounts"][1]["Source"] = "/wrong/identity.json"
                elif field == "identity-writeable":
                    current["Mounts"][1]["RW"] = True
                elif field == "health":
                    current["State"]["Health"]["Status"] = "unhealthy"
                else:
                    current["State"]["Running"] = False
                self.release.containers["minio"] = current
                with self.assertRaises(ReleaseError):
                    self.fence.restore()
                self.assert_no_starts()

    def test_missing_provider_fails_with_checkpoint_and_recovery_path(self):
        self.begin()
        self.stop_writers()
        del self.release.containers["minio"]
        with self.assertRaisesRegex(ReleaseError, "Do not choose an empty volume or roll back target writes"):
            self.fence.restore()
        self.assert_no_starts()

    def test_proof_or_identity_tampering_blocks_target_recovery(self):
        self.begin()
        self.stop_writers()
        self.proof()
        self.switch_target()
        for path in (self.release.proof_path, self.release.identity_path):
            with self.subTest(path=path.name):
                old = path.read_text()
                path.write_text(old + " ")
                with self.assertRaises(ReleaseError):
                    self.fence.restore()
                self.assert_no_starts()
                path.write_text(old)

    def test_staging_cannot_share_open_target_metadata_store(self):
        self.begin()
        self.stop_writers()
        self.proof()
        self.switch_target()
        stage = self.release.make("storage-stage")
        stage["Mounts"] = [{"Type": "volume", "Name": "verified-target-volume", "Destination": "/data"}]
        self.release.containers["storage-stage"] = stage
        with self.assertRaisesRegex(ReleaseError, "Staging still"):
            self.fence.restore()
        self.assert_no_starts()

    def test_all_writer_identities_verified_before_any_restart(self):
        self.begin()
        self.stop_writers()
        old = copy.deepcopy(self.release.containers["backend"])
        for field in ("id", "image", "project", "directory"):
            with self.subTest(field=field):
                current = copy.deepcopy(old)
                if field in {"id", "image"}:
                    current[{"id": "Id", "image": "Image"}[field]] = "replacement"
                else:
                    label = PROJECT_LABEL if field == "project" else "com.docker.compose.project.working_dir"
                    current["Config"]["Labels"][label] = "other"
                self.release.containers["backend"] = current
                with self.assertRaises(ReleaseError):
                    self.fence.restore()
                self.assert_no_starts()

    def test_nginx_reload_failure_retains_checkpoint_and_retry_does_not_restart_running_writers(self):
        self.begin()
        self.stop_writers()
        self.release.fail_reload = True
        with self.assertRaisesRegex(ReleaseError, "nginx reload failure"):
            self.fence.restore()
        self.assertEqual(json.loads(self.fence.path.read_text())["phase"], "fencing")
        self.release.calls.clear()
        self.release.fail_reload = False
        recover_pending_storage_writers(self.release)
        self.assert_no_starts()
        self.assertEqual(json.loads(self.fence.path.read_text())["phase"], "complete")

    def test_partial_restart_failure_is_recoverable_without_duplicate_starts(self):
        self.begin()
        self.stop_writers()
        self.release.fail_start_after = 1
        with self.assertRaisesRegex(ReleaseError, "partial Docker start failure"):
            self.fence.restore()
        self.assertTrue(self.release.containers["worker"]["State"]["Running"])
        self.release.fail_start_after = None
        self.release.calls.clear()
        self.fence.restore()
        starts = [call for call in self.release.calls if call[:2] == ("docker", "start")]
        self.assertEqual(starts, [("docker", "start", "email-beat-original-id", "backend-original-id")])

    def test_incomplete_writer_inventory_is_not_accepted(self):
        self.begin()
        self.stop_writers()
        record = json.loads(self.fence.path.read_text())
        record["writers"].pop()
        self.fence.path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ReleaseError, "incomplete"):
            self.fence.restore()
        self.assert_no_starts()

    def test_pending_other_revision_is_not_silently_recovered(self):
        self.begin()
        self.release.revision = "b" * 40
        with self.assertRaisesRegex(ReleaseError, "different or invalid release"):
            self.fence.restore()
        self.assert_no_starts()

    def test_recovery_rechecks_hostname_and_network_identity_before_restarting(self):
        self.begin()
        self.stop_writers()
        original = copy.deepcopy(self.release.containers["backend"])
        for changed in ("extra-host", "network"):
            with self.subTest(changed=changed):
                backend = copy.deepcopy(original)
                if changed == "extra-host":
                    backend["HostConfig"]["ExtraHosts"] = ["minio:203.0.113.42"]
                else:
                    backend["NetworkSettings"]["Networks"]["synthetic-net"]["NetworkID"] = "different"
                self.release.containers["backend"] = backend
                with self.assertRaises(ReleaseError):
                    self.fence.restore()
                self.assert_no_starts()

    def test_completed_previous_revision_does_not_block_next_release(self):
        self.begin()
        self.fence.restore()
        self.release.revision = "b" * 40
        recover_pending_storage_writers(self.release)
        self.begin()
        self.assertEqual(json.loads(self.fence.path.read_text())["revision"], "b" * 40)

    def test_pending_fence_cannot_be_overwritten(self):
        self.begin()
        with self.assertRaisesRegex(ReleaseError, "unfinished"):
            self.begin()

    def test_target_handoff_requires_verified_preservation_proof(self):
        self.begin()
        with self.assertRaisesRegex(ReleaseError, "verified target"):
            self.fence.begin_handoff()
        self.assert_no_starts()


if __name__ == "__main__":
    unittest.main()
