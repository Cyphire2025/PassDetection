"""Dataset reductions preserve values/TTL and recover only exact checkpoints."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import release_redis_dataset_transition as transition
from release_persistent_resources import _target
from release_traveller_whatsapp import ReleaseError
from test_release_persistent_resources import PersistentFixture


class DatasetFixture(PersistentFixture):
    def __init__(self, directory, service):
        super().__init__()
        self.directory = Path(directory)
        self.revision = "a" * 40
        self.service = service
        self.before = {"databases": 16, "now_ms": 1000, "rows": {"0:key": ["value", -1], "1:ttl": ["expires", 10000]}}
        self.after = copy.deepcopy(self.before)
        self.files = {}
        self.interrupt_after_start = False
        self.interrupt_after_archive = False
        self.restarts = 0
        original = self.containers[service]
        old, new, cap = transition.LIMITS[service]
        command = ["redis-server", "--requirepass", "private", "--maxmemory", str(old),
                   "--maxmemory-policy", "noeviction" if service == "redis-broker" else "allkeys-lru",
                   "--appendonly", "yes" if service == "redis-broker" else "no"]
        command += ["--appendfsync", "everysec"] if service == "redis-broker" else ["--save", ""]
        original["Config"]["Cmd"] = command
        reference = "redis:7-alpine@" + original["Image"]
        self.images[reference] = {"Id": original["Image"], "Config": copy.deepcopy(original["Config"])}
        spec = self.config["services"][service]
        spec.update(image=reference, command=command.copy(), mem_limit=cap, memswap_limit=cap)
        spec["command"][spec["command"].index("--maxmemory") + 1] = str(new)
        self.record["persistent"][service] = _target(self, self, self.config, service)

    def write_private(self, path, value, **kwargs):
        Path(path).write_text(value)

    def run(self, *args, **kwargs):
        if args[:2] == ("docker", "exec"):
            self.calls.append(args)
            if args[3] == "sha256sum":
                return self.files[args[4]] + "  " + args[4]
            if args[3:5] == ("sh", "-c"):
                source, destination = args[-2:]
                script = args[5]
                if script.startswith("test ! -e"):
                    if destination in self.files or ("mv" not in script and source in self.files):
                        raise ReleaseError("snapshot path already exists")
                    if "mv" in script:
                        self.files[destination] = self.files.pop(source)
                        if self.interrupt_after_archive:
                            self.interrupt_after_archive = False
                            raise ReleaseError("interrupted after archive")
                    return ""
                return "source" if source in self.files else "archive"
        if args[:2] == ("docker", "compose"):
            self.calls.append(args)
            self.restarts += 1
            current = self.containers.setdefault(self.service, copy.deepcopy(self.record["persistent"][self.service]["original"]))
            spec = self.config["services"][self.service]
            current["Id"] = self.service + "-candidate"
            current["Config"]["Cmd"] = spec["command"].copy()
            current["State"].update(Running=True, Pid=999, StartedAt="new-start", ExitCode=0)
            current["HostConfig"].update(Memory=spec["mem_limit"], MemorySwap=spec["memswap_limit"], NanoCpus=500_000_000)
            if self.interrupt_after_start:
                self.interrupt_after_start = False
                raise ReleaseError("interrupted after start")
            return ""
        return super().run(*args, **kwargs)

    def cli(self, release, container, *args, **kwargs):
        if args == ("INFO", "memory"):
            return "used_memory:1000000"
        if args == ("SAVE",):
            self.files["/data/dump.rdb"] = "d" * 64
            return "OK"
        raise AssertionError(args)

    def redis_fingerprint(self, release, container):
        return copy.deepcopy(self.before if container["Id"].endswith("-original") else self.after)


class DatasetTransitionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def fixture(self, service="redis-cache"):
        fixture = DatasetFixture(self.directory.name, service)
        patches = [patch.object(transition, "_runtime"), patch.object(transition, "_cli", side_effect=fixture.cli),
                   patch.object(transition, "fingerprint", side_effect=fixture.redis_fingerprint),
                   patch("release_persistent_resources.cgroup_memory", side_effect=lambda _: copy.deepcopy(fixture.memory))]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        return fixture

    def apply(self, fixture):
        transition.transition_dataset(fixture, fixture, fixture.record, fixture.service)

    def test_only_reviewed_maxmemory_delta_is_accepted(self):
        fixture = self.fixture("redis-broker")
        old = fixture.containers[fixture.service]["Config"]["Cmd"]
        new = fixture.config["services"][fixture.service]["command"]
        self.assertIsNotNone(transition.reviewed_transition("redis-broker", old, new, 896 * 1024**2))
        for kind, changed in (("auth", new + ["--requirepass", "changed"]), ("policy", new + ["--maxmemory-policy", "allkeys-lru"]),
                              ("extra", new + ["--appendonly", "no"]), ("duplicate", new + ["--maxmemory", "384mb"])):
            with self.subTest(kind=kind):
                self.assertIsNone(transition.reviewed_transition("redis-broker", old, changed, 896 * 1024**2))
        self.assertIsNone(transition.reviewed_transition("redis", old, new, 896 * 1024**2))

    def test_broker_preserves_volume_and_queue_values(self):
        fixture = self.fixture("redis-broker")
        before = copy.deepcopy(fixture.volumes)
        self.apply(fixture)
        self.assertEqual(fixture.restarts, 1)
        self.assertEqual(fixture.record["persistent"][fixture.service]["stage"], "complete")
        self.assertEqual(fixture.volumes, before)
        self.assertIn("/data/dump.rdb", fixture.files)
        self.apply(fixture)
        self.assertEqual(fixture.restarts, 1)

    def test_cache_snapshot_is_retained_but_removed_from_future_default_load_path(self):
        fixture = self.fixture()
        self.apply(fixture)
        entry = fixture.record["persistent"][fixture.service]
        self.assertNotIn("/data/dump.rdb", fixture.files)
        self.assertEqual(fixture.files[entry["cache_archive"]], "d" * 64)
        override = json.loads(next(Path(self.directory.name).glob("*.retained-volume.json")).read_text())
        self.assertEqual(override["volumes"]["retained_redis_cache"]["name"], "redis-cache-retained-data")
        self.assertTrue(override["volumes"]["retained_redis_cache"]["external"])

    def test_interrupted_replacement_adopts_only_exact_candidate_without_second_restart(self):
        fixture = self.fixture()
        fixture.interrupt_after_start = True
        with self.assertRaisesRegex(ReleaseError, "after start"):
            self.apply(fixture)
        self.assertEqual(fixture.record["persistent"][fixture.service]["stage"], "redis_starting")
        self.apply(fixture)
        self.assertEqual(fixture.restarts, 1)

    def test_interrupted_archive_resumes_without_losing_snapshot(self):
        fixture = self.fixture()
        fixture.interrupt_after_archive = True
        with self.assertRaisesRegex(ReleaseError, "after archive"):
            self.apply(fixture)
        self.apply(fixture)
        self.assertEqual(fixture.record["persistent"][fixture.service]["stage"], "complete")

    def test_removed_container_can_be_recreated_only_in_recorded_starting_stage(self):
        fixture = self.fixture()
        fixture.interrupt_after_start = True
        with self.assertRaises(ReleaseError):
            self.apply(fixture)
        fixture.containers.pop(fixture.service)
        self.apply(fixture)
        self.assertEqual(fixture.record["persistent"][fixture.service]["stage"], "complete")

    def test_value_change_after_verified_checkpoint_is_rejected(self):
        fixture = self.fixture()
        fixture.interrupt_after_archive = True
        with self.assertRaises(ReleaseError):
            self.apply(fixture)
        fixture.after["rows"]["0:key"] = ["intervening-change", -1]
        with self.assertRaisesRegex(ReleaseError, "value or absolute TTL"):
            self.apply(fixture)

    def test_missing_unexpired_key_or_changed_value_or_ttl_stays_fenced(self):
        fixture = self.fixture()
        fixture.after["rows"].pop("0:key")
        with self.assertRaisesRegex(ReleaseError, "lost an unexpired"):
            self.apply(fixture)
        self.assertEqual(fixture.record["persistent"][fixture.service]["stage"], "redis_starting")
        fixture.after = copy.deepcopy(fixture.before)
        fixture.after["rows"]["0:key"] = ["modified", -1]
        with self.assertRaisesRegex(ReleaseError, "value or absolute TTL"):
            self.apply(fixture)

    def test_natural_expiry_is_allowed_but_unexpired_key_loss_is_not(self):
        before = {"databases": 1, "now_ms": 1000, "rows": {"key": ["value", 1500]}}
        transition.compare_fingerprints(before, {"databases": 1, "now_ms": 1600, "rows": {}})
        with self.assertRaisesRegex(ReleaseError, "unexpired"):
            transition.compare_fingerprints(before, {"databases": 1, "now_ms": 1400, "rows": {}})

    def test_preexisting_snapshot_or_memory_pressure_prevents_stop(self):
        fixture = self.fixture()
        fixture.files["/data/dump.rdb"] = "existing-data"
        with self.assertRaisesRegex(ReleaseError, "already exists"):
            self.apply(fixture)
        self.assertTrue(fixture.containers[fixture.service]["State"]["Running"])
        self.assertEqual(fixture.restarts, 0)

    def test_changed_volume_on_recovery_is_refused(self):
        fixture = self.fixture()
        fixture.interrupt_after_start = True
        with self.assertRaises(ReleaseError):
            self.apply(fixture)
        fixture.volumes["redis-cache-retained-data"]["CreatedAt"] = "different"
        with self.assertRaisesRegex(ReleaseError, "volume identity"):
            self.apply(fixture)

    def test_memory_pressure_refuses_snapshot_and_stop(self):
        fixture = self.fixture()
        fixture.memory["current"] = 180 * 1024**2
        with self.assertRaisesRegex(ReleaseError, "container headroom"):
            self.apply(fixture)
        self.assertTrue(fixture.containers[fixture.service]["State"]["Running"])
        self.assertEqual(fixture.files, {})


if __name__ == "__main__":
    unittest.main()
