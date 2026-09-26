"""Data-preserving resource change and interruption boundaries."""
from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import patch

from release_persistent_resources import (
    ORDER,
    REDIS,
    apply_persistent_resources,
    recover_persistent_resources,
)
from release_traveller_whatsapp import ReleaseError

DB_IDENTITY = {"system_identifier": "retained-cluster", "database": "application", "major": 16,
               "data_directory": "/var/lib/postgresql/data"}
FINGERPRINT = {"identity": DB_IDENTITY, "table_count": 2, "sequence_count": 1, "sha256": "all-original-data"}


class PersistentFixture:
    def __init__(self):
        self.compose = ["docker", "compose", "-p", "isolated-fixture"]
        self.calls = []
        self.backups_path = "verified-private-evidence"
        self.containers = {}
        self.images = {}
        self.volumes = {}
        self.config = {"services": {}, "volumes": {}}
        self.record = {"phase": "maintenance", "persistent": {}}
        self.backup_valid = True
        self.update_failure = False
        self.start_failure = False
        self.memory = {"current": 20 * 1024**2, "oom": 0, "oom_kill": 0}
        self.fingerprint = copy.deepcopy(FINGERPRINT)
        self.identity = copy.deepcopy(DB_IDENTITY)
        self.stopped = True
        for index, name in enumerate(ORDER, 1):
            image_id = "sha256:" + str(index) * 64
            reference = ("postgres:16-alpine" if name == "db" else "fixture:" + name) + "@" + image_id
            target = "/var/lib/postgresql/data" if name == "db" else "/data"
            volume = name + "-retained-data"
            env = ["POSTGRES_DB=application", "POSTGRES_USER=bootstrap", "POSTGRES_PASSWORD=private", "PGDATA=" + target] if name == "db" else []
            command = ["redis-server", "--requirepass", "private"] if name in REDIS else [name]
            self.containers[name] = {
                "Id": name + "-original", "Image": image_id, "RestartCount": 0,
                "Config": {"Env": env, "Cmd": command, "Entrypoint": ["entry"]},
                "State": {"Running": True, "Paused": False, "Pid": index, "StartedAt": "original-start", "ExitCode": 0,
                          "OOMKilled": False, "Health": {"Status": "healthy"}},
                "HostConfig": {"Memory": 512 * 1024**2, "MemorySwap": 1024 * 1024**2, "NanoCpus": 1_000_000_000},
                "Mounts": [{"Type": "volume", "Name": volume, "Source": "/volumes/" + volume,
                            "Destination": target, "RW": True}],
            }
            self.images[reference] = {"Id": image_id, "Config": copy.deepcopy(self.containers[name]["Config"])}
            self.volumes[volume] = {"Name": volume, "Driver": "local", "Mountpoint": "/volumes/" + volume,
                                    "CreatedAt": "original-volume", "Labels": {}, "Options": None, "Scope": "local"}
            self.config["volumes"][volume] = {"name": volume}
            self.config["services"][name] = {"image": reference, "command": command, "mem_limit": 256 * 1024**2,
                                              "cpus": "0.5", "volumes": [{"type": "volume", "source": volume, "target": target}],
                                              "environment": dict(value.split("=", 1) for value in env)}

    def inspect(self, identity, *, image=False):
        if image:
            return copy.deepcopy(self.images[identity])
        return copy.deepcopy(next(value for value in self.containers.values() if value["Id"] == identity))

    def existing(self, service):
        return copy.deepcopy(self.containers[service])

    def run(self, *args, **kwargs):
        self.calls.append(args)
        if args[:3] == ("docker", "volume", "inspect"):
            return json.dumps([self.volumes[args[-1]]])
        if args[:2] == ("docker", "ps"):
            service = args[-1].rsplit("=", 1)[1]
            return self.containers.get(service, {}).get("Id", "")
        container = next(value for value in self.containers.values() if value["Id"] == args[-1])
        if args[1] == "pause":
            container["State"]["Paused"] = True
        elif args[1] == "unpause":
            container["State"]["Paused"] = False
        elif args[1] == "stop":
            container["State"]["Running"] = False
        elif args[1] == "update":
            if self.update_failure:
                raise ReleaseError("Docker update interrupted")
            container["HostConfig"].update(Memory=int(args[3]), MemorySwap=int(args[5]), NanoCpus=int(float(args[7]) * 1_000_000_000))
        else:
            raise AssertionError(args)
        return ""

    def dc(self, *args, **kwargs):
        self.calls.append(("compose", *args))
        name = args[-1]
        original = self.containers[name]
        spec = self.config["services"][name]
        current = copy.deepcopy(original)
        current["Id"] = name + "-candidate"
        current["Image"] = self.images[spec["image"]]["Id"]
        current["State"].update(Running=True, ExitCode=0)
        current["HostConfig"].update(Memory=spec["mem_limit"], MemorySwap=spec["mem_limit"] * 2,
                                    NanoCpus=int(float(spec["cpus"]) * 1_000_000_000))
        self.containers[name] = current
        if self.start_failure and name == "db":
            self.start_failure = False
            raise ReleaseError("Compose process interrupted after creating database")
        return ""

    def _load_evidence(self, path):
        return {"backups": [{"archive": "verified"}]}

    def _validate_backup_record(self, record):
        if not self.backup_valid:
            raise ReleaseError("Backup integrity failure")

    def load(self):
        return copy.deepcopy(self.record)

    def save(self, record):
        self.record = copy.deepcopy(record)

    def verify_binding(self, config):
        if config != self.config:
            raise ReleaseError("Changed prepared configuration")

    def assert_stopped(self):
        if not self.stopped:
            raise ReleaseError("Writer still running")

    def sql(self, sql):
        return json.dumps(self.identity)


class PersistentResourceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = PersistentFixture()
        self.memory = patch("release_persistent_resources.cgroup_memory", side_effect=lambda item: copy.deepcopy(self.fixture.memory))
        self.fingerprint = patch("release_persistent_resources.database_fingerprint", side_effect=lambda fence: copy.deepcopy(self.fixture.fingerprint))
        self.memory.start()
        self.fingerprint.start()
        self.addCleanup(self.memory.stop)
        self.addCleanup(self.fingerprint.stop)

    def apply(self):
        apply_persistent_resources(self.fixture, self.fixture, self.fixture.config)

    def test_success_preserves_all_redis_processes_and_all_volumes(self):
        before = copy.deepcopy(self.fixture.volumes)
        self.apply()
        for name in REDIS:
            self.assertEqual(self.fixture.containers[name]["Id"], name + "-original")
            self.assertFalse(self.fixture.containers[name]["State"]["Paused"])
        self.assertEqual(before, self.fixture.volumes)
        self.assertTrue(all(entry["stage"] == "complete" for entry in self.fixture.record["persistent"].values()))
        self.assertFalse(any("rm" in call or "down" in call or "restart" in call for call in self.fixture.calls))

    def test_all_targets_validate_before_first_mutation(self):
        self.fixture.config["volumes"]["db-retained-data"]["name"] = "empty-other-volume"
        with self.assertRaisesRegex(ReleaseError, "volume mapping"):
            self.apply()
        self.assertFalse(any(call[1] in {"pause", "stop", "update"} for call in self.fixture.calls))

    def test_missing_verified_backup_prevents_every_mutation(self):
        self.fixture.backup_valid = False
        with self.assertRaisesRegex(ReleaseError, "Backup integrity"):
            self.apply()
        self.assertEqual(self.fixture.calls, [])

    def test_busy_memory_unpauses_identical_process_and_never_restarts(self):
        self.fixture.memory["current"] = 250 * 1024**2
        with self.assertRaisesRegex(ReleaseError, "headroom"):
            self.apply()
        self.assertFalse(self.fixture.containers["redis"]["State"]["Paused"])
        self.assertEqual(self.fixture.containers["redis"]["HostConfig"]["Memory"], 512 * 1024**2)
        self.assertFalse(any(call[1] == "update" for call in self.fixture.calls))

    def test_failed_docker_update_unpauses_and_retry_preserves_same_process(self):
        self.fixture.update_failure = True
        with self.assertRaisesRegex(ReleaseError, "Docker update"):
            self.apply()
        self.assertFalse(self.fixture.containers["redis"]["State"]["Paused"])
        self.fixture.update_failure = False
        recover_persistent_resources(self.fixture, self.fixture)
        self.assertEqual(self.fixture.containers["redis"]["Id"], "redis-original")

    def test_recovery_detects_external_redis_restart(self):
        self.fixture.update_failure = True
        with self.assertRaises(ReleaseError):
            self.apply()
        self.fixture.containers["redis"]["RestartCount"] += 1
        with self.assertRaisesRegex(ReleaseError, "Redis process"):
            recover_persistent_resources(self.fixture, self.fixture)

    def test_database_bootstrap_or_pgdata_change_rejected_before_mutation(self):
        self.fixture.config["services"]["db"]["environment"]["PGDATA"] = "/empty"
        with self.assertRaisesRegex(ReleaseError, "bootstrap identity or PGDATA"):
            self.apply()
        self.assertFalse(any(call[1] in {"pause", "stop", "update"} for call in self.fixture.calls))

    def test_existing_extra_bind_cannot_be_silently_discarded(self):
        self.fixture.containers["db"]["Mounts"].append({"Type": "bind", "Source": "/private-certs", "Destination": "/certs", "RW": False})
        with self.assertRaisesRegex(ReleaseError, "unreviewed existing mount"):
            self.apply()
        self.assertFalse(any(call[1] in {"pause", "stop", "update"} for call in self.fixture.calls))

    def test_database_interruption_resumes_without_restore_or_rollback(self):
        self.fixture.start_failure = True
        with self.assertRaisesRegex(ReleaseError, "Compose process"):
            self.apply()
        recover_persistent_resources(self.fixture, self.fixture)
        self.assertEqual(self.fixture.record["persistent"]["db"]["stage"], "complete")
        self.assertTrue(self.fixture.stopped)

    def test_database_changed_content_refuses_completion(self):
        self.fixture.start_failure = True
        with self.assertRaises(ReleaseError):
            self.apply()
        self.fixture.fingerprint["sha256"] = "missing-or-modified-records"
        with self.assertRaisesRegex(ReleaseError, "Database contents"):
            recover_persistent_resources(self.fixture, self.fixture)
        self.assertTrue(self.fixture.stopped)

    def test_volume_replacement_is_not_adopted_on_retry(self):
        self.fixture.start_failure = True
        with self.assertRaises(ReleaseError):
            self.apply()
        self.fixture.volumes["db-retained-data"]["CreatedAt"] = "new-empty-volume"
        with self.assertRaisesRegex(ReleaseError, "volume was replaced"):
            recover_persistent_resources(self.fixture, self.fixture)

    def test_complete_retry_allows_additive_migrations_but_binds_cluster(self):
        self.apply()
        self.fixture.fingerprint["sha256"] = "legitimate-new-migration-and-data"
        recover_persistent_resources(self.fixture, self.fixture)
        self.fixture.identity["system_identifier"] = "new-empty-cluster"
        with self.assertRaisesRegex(ReleaseError, "cluster identity changed"):
            recover_persistent_resources(self.fixture, self.fixture)

    def test_running_application_writer_prevents_all_maintenance(self):
        self.fixture.stopped = False
        with self.assertRaisesRegex(ReleaseError, "Writer still running"):
            self.apply()
        self.assertEqual(self.fixture.calls, [])


if __name__ == "__main__":
    unittest.main()
