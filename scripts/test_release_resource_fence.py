"""Failure boundaries of the durable outer maintenance fence, without Docker writes."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from release_resource_fence import ResourceFence
from release_traveller_whatsapp import ReleaseError
from test_storage_writer_fence import FenceDocker


class ResourceDocker(FenceDocker):
    def __init__(self, root):
        super().__init__(root)
        self.activated_services = (*self.workers, "backend", "frontend")
        self.node_prefixes = {"worker": "general"}
        self.expected_schema = "0111_roster_revision"
        self.containers["frontend"] = self.make("frontend")
        self.manifest_path = self.directory / "prepared.json"
        self.manifest_path.write_text(json.dumps({"images": {name: name + "-new-image" for name in self.activated_services}}))
        self.resources = ResourceFence(self)
        self.fingerprint = "prepared-private-config-digest"
        self.busy = False
        self.stop_crash = None
        self.unclean = None

    def config_fingerprint(self, config):
        return self.fingerprint

    def probe_running_workers_idle(self):
        assert not self.containers["backend"]["State"]["Running"]
        assert not self.containers["email-beat"]["State"]["Running"]
        self.calls.append(("drain",))
        if self.busy:
            raise ReleaseError("Accepted job still active")

    def run(self, *args, **kwargs):
        if args[:2] == ("docker", "stop") and self.stop_crash == args[-1]:
            self.stop_crash = None
            raise ReleaseError("Interrupted Docker stop")
        result = super().run(*args, **kwargs)
        if args[:2] == ("docker", "stop") and self.unclean == args[-1]:
            for item in self.containers.values():
                if item["Id"] == args[-1]:
                    item["State"]["ExitCode"] = 137
        return result


class ResourceFenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.release = ResourceDocker(Path(self.directory.name).resolve())
        self.fence = self.release.resources

    def test_ingress_and_beat_stop_before_drain_and_no_automatic_restart(self):
        self.fence.begin({})
        self.fence.assert_stopped()
        calls = self.release.calls
        drain = calls.index(("drain",))
        worker_stop = next(i for i, call in enumerate(calls) if call[:2] == ("docker", "stop") and call[-1] == "worker-original-id")
        self.assertLess(drain, worker_stop)
        self.assertFalse(any(call[:2] == ("docker", "start") for call in calls))
        self.assertEqual(self.fence.load()["phase"], "maintenance")

    def test_busy_accepted_work_keeps_consumers_alive_and_blocks_maintenance(self):
        self.release.busy = True
        with self.assertRaisesRegex(ReleaseError, "Accepted job"):
            self.fence.begin({})
        self.assertTrue(self.release.containers["worker"]["State"]["Running"])
        self.assertFalse(self.release.containers["backend"]["State"]["Running"])
        self.release.busy = False
        self.fence.begin({})
        self.fence.assert_stopped()

    def test_interrupted_stop_is_retried_using_original_identities(self):
        self.release.stop_crash = "worker-original-id"
        with self.assertRaisesRegex(ReleaseError, "Interrupted"):
            self.fence.begin({})
        self.assertTrue(self.fence.load()["workers_drained"])
        self.fence.begin({})
        self.fence.assert_stopped()
        self.assertEqual(sum(call == ("drain",) for call in self.release.calls), 2)

    def test_unclean_exit_does_not_authorize_helpers_or_restart(self):
        self.release.unclean = "worker-original-id"
        with self.assertRaisesRegex(ReleaseError, "cleanly"):
            self.fence.begin({})
        with self.assertRaisesRegex(ReleaseError, "cleanly"):
            self.fence.assert_stopped()

    def test_changed_configuration_project_image_and_mount_refuse_retry(self):
        self.fence.begin({})
        self.release.fingerprint = "changed"
        with self.assertRaisesRegex(ReleaseError, "configuration changed"):
            self.fence.begin({})
        self.release.fingerprint = "prepared-private-config-digest"
        original = copy.deepcopy(self.release.containers["worker"])
        for mutation in ({"Image": "different"}, {"Mounts": [{"Type": "volume", "Name": "empty", "Destination": "/data"}]}):
            self.release.containers["worker"].update(mutation)
            with self.assertRaisesRegex(ReleaseError, "identity changed"):
                self.fence.assert_stopped()
            self.release.containers["worker"] = copy.deepcopy(original)
        self.release.compose[3] = "different-project"
        with self.assertRaisesRegex(ReleaseError, "configuration changed"):
            self.fence.begin({})

    def test_partial_new_activation_is_refenced_without_old_image_rollback(self):
        self.fence.begin({})
        self.fence.start_activation()
        new = self.release.make("worker", identifier="worker-new-id", image="worker-new-image")
        new["Config"]["Env"] = [f"APP_REVISION={self.release.revision}", f"EXPECTED_DATABASE_SCHEMA_REVISION={self.release.expected_schema}"]
        self.release.containers["worker"] = new
        self.fence.begin({})
        self.fence.assert_stopped()
        self.assertEqual(self.release.containers["worker"]["Id"], "worker-new-id")
        self.assertFalse(any(call[:2] == ("docker", "start") for call in self.release.calls))

    def test_unprepared_replacement_is_never_adopted(self):
        self.fence.begin({})
        self.fence.start_activation()
        self.release.containers["worker"] = self.release.make("worker", identifier="foreign", image="unreviewed")
        with self.assertRaisesRegex(ReleaseError, "not this prepared release"):
            self.fence.begin({})

    def test_stopped_backend_retains_verified_original_network_for_backup_binding(self):
        self.fence.begin({})
        expected = copy.deepcopy(self.release.containers["backend"]["NetworkSettings"])
        self.release.containers["backend"]["NetworkSettings"] = {"Networks": {}}
        self.assertEqual(self.fence.container("backend")["NetworkSettings"], expected)

    def test_only_recorded_activation_can_complete(self):
        self.fence.begin({})
        with self.assertRaisesRegex(ReleaseError, "unrecorded"):
            self.fence.complete()
        self.fence.start_activation()
        self.fence.complete()
        self.assertFalse(self.fence.active())

    def test_storage_recovery_leaves_writers_under_outer_fence_stopped(self):
        from storage_writer_fence import StorageWriterFence
        self.fence.begin({})
        storage = StorageWriterFence(self.release)
        writers = [self.release.container(name) for name in (*self.release.workers, "backend")]
        storage.begin(self.release.container("minio"), writers, self.release.config, "new-provider", "copy-image")
        storage.restore()
        self.assertTrue(json.loads(storage.path.read_text())["writers_left_stopped_for_resource_maintenance"])
        self.fence.assert_stopped()
        self.assertFalse(any(call[:2] == ("docker", "start") for call in self.release.calls))

    def test_final_verification_checks_unchanged_infrastructure_caps_and_swap(self):
        config = {"services": {name: {"mem_limit": "128m", "cpus": 1} for name in self.release.containers}}
        for item in self.release.containers.values():
            item["HostConfig"].update(Memory=128 * 1024**2, MemorySwap=128 * 1024**2, NanoCpus=10**9)
        original_run = self.release.run

        def inventory(*args, **kwargs):
            if args == ("docker", "ps", "--quiet"):
                return "\n".join(item["Id"] for item in self.release.containers.values())
            if args == ("docker", "info", "--format", "{{.MemTotal}}"):
                return str(8 * 1024**3)
            return original_run(*args, **kwargs)

        with patch.object(self.release, "run", side_effect=inventory):
            self.fence.verify_actual_limits(config, exact=True)
            self.release.containers["nginx"]["HostConfig"]["MemorySwap"] = 256 * 1024**2
            self.fence.verify_actual_limits(config, exact=True)
            self.release.containers["nginx"]["HostConfig"]["MemorySwap"] = 384 * 1024**2
            with self.assertRaisesRegex(ReleaseError, "nginx: actual"):
                self.fence.verify_actual_limits(config, exact=True)
            self.release.containers["nginx"]["HostConfig"]["Memory"] = 0
            with self.assertRaises(ValueError):
                self.fence.verify_actual_limits(config, exact=False)


if __name__ == "__main__":
    unittest.main()
