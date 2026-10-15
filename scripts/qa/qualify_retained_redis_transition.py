"""Synthetic, isolated proof of the actual retained Redis resource adapter."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mcp_direct_containers import LocalDocker
from qa.qualify_redis_dataset_transition import LABEL, Fixture, guard
from release_document_resources import RetainedRedis
from release_persistent_resources import _target
from release_redis_dataset_transition import (
    _cli,
    compare_fingerprints,
    fingerprint,
    transition_dataset,
)


class RetainedFixture(Fixture):
    def __init__(self, directory, service, image):
        super().__init__(directory, service, image)
        spec = self.config["services"][service]
        spec.pop("network_mode")
        spec["networks"] = {"isolated": {"aliases": [service]}}
        self.config["networks"] = {"isolated": {"name": self.project + "-isolated", "internal": True,
                                                 "labels": {LABEL: self.project}}}
        self.compose_path.write_text(json.dumps(self.config))

    def existing(self, service):
        if hasattr(self, "adapter"):
            return self.adapter.existing(service)
        ids = self.run("docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={self.project}",
                       "--filter", f"label=com.docker.compose.service={service}").split()
        assert len(ids) == 1
        return self.inspect(ids[0])

    def cleanup(self):
        self.cleaning = True
        for identifier in self.run("docker", "ps", "-aq", "--filter", f"label={LABEL}={self.project}").split():
            value = self.inspect(identifier)
            assert value["Config"]["Labels"][LABEL] == self.project
            assert set(value["NetworkSettings"]["Networks"]) == {self.project + "-isolated"}
            self.run("docker", "rm", "-f", identifier)
        for volume in self.run("docker", "volume", "ls", "-q", "--filter", f"label={LABEL}={self.project}").split():
            value = json.loads(self.run("docker", "volume", "inspect", volume))[0]
            assert volume == self.project + "-data" and value["Labels"][LABEL] == self.project
            self.run("docker", "volume", "rm", volume)
        for network in self.run("docker", "network", "ls", "-q", "--filter", f"label={LABEL}={self.project}").split():
            value = json.loads(self.run("docker", "network", "inspect", network))[0]
            assert value["Name"] == self.project + "-isolated" and value["Labels"][LABEL] == self.project
            assert value["Internal"] and not value["Containers"]
            self.run("docker", "network", "rm", network)

    def probe_retained(self):
        try:
            self.run(*self.compose, "up", "-d", "--pull", "never", "--wait", "--wait-timeout", "45")
            original = self.existing(self.service)
            for args in (("SET", "string", "synthetic"), ("RPUSH", "queue", "one", "two"),
                         ("HSET", "hash", "b", "two", "a", "one"), ("SADD", "set", "b", "a"),
                         ("ZADD", "sorted", "2", "b", "1", "a"), ("SET", "lease", "live", "PX", "900000")):
                _cli(self, original, *args)
            _cli(self, original, "SET", "other-database", "retained", database=1)
            before = fingerprint(self, original)
            spec = self.config["services"][self.service]
            maximum, cap = (384, 896) if self.service == "redis-broker" else (128, 192)
            spec["command"][spec["command"].index("--maxmemory") + 1] = f"{maximum}mb"
            spec.update(mem_limit=f"{cap}m", memswap_limit=f"{cap}m")
            # _target only inspects/validates. Creation uses RetainedRedis below.
            self.record["persistent"][self.service] = _target(self, self, self.config, self.service)
            release = SimpleNamespace(directory=self.directory, revision=self.revision,
                                      project=self.project + "-next", source=self.directory,
                                      record=self.record, client=LocalDocker())
            release.event = lambda phase, **values: self.record.update(phase=phase, **values)
            def rows(*, all=False):
                ids = self.run("docker", "ps", "-aq" if all else "-q", "--filter", f"label={LABEL}={self.project}").split()
                return [self.inspect(identifier) for identifier in ids]
            release.rows = rows
            def fenced():
                guard()
                assert all(row["Config"]["Labels"]["com.docker.compose.service"] == self.service for row in rows(all=True))
                assert sum(row["State"]["Running"] for row in rows(all=True)) <= 1
            release.assert_writer_fence = fenced
            self.adapter = RetainedRedis(release)
            entry = self.record["persistent"][self.service]
            # Simulate process death after create has committed but before the
            # replacement checkpoint. Resume must bind the stopped orphan.
            request = release.client.request
            interrupted = False
            def create_then_interrupt(method, path, payload=None, **kwargs):
                nonlocal interrupted
                value = request(method, path, payload, **kwargs)
                if method == "POST" and path.startswith("/containers/create") and not interrupted:
                    interrupted = True
                    raise RuntimeError("synthetic_retained_create_interruption")
                return value
            release.client.request = create_then_interrupt
            with patch("release_document_resources.command", self.run):
                try:
                    transition_dataset(self.adapter, self.adapter, self.record, self.service)
                except RuntimeError as error:
                    assert str(error) == "synthetic_retained_create_interruption"
                assert interrupted and entry["stage"] == "redis_starting"
                transition_dataset(self.adapter, self.adapter, self.record, self.service)
                transition_dataset(self.adapter, self.adapter, self.record, self.service)
            current = self.adapter.existing(self.service)
            compare_fingerprints(before, fingerprint(self, current))
            assert not self.inspect(original["Id"])["State"]["Running"]
            assert current["Id"] != original["Id"] and entry["stage"] == "complete"
            assert len(rows(all=True)) == 2 and len(rows()) == 1
            relative = (Path("/proc") / str(current["State"]["Pid"]) / "cgroup").read_text().split("::")[-1].strip()
            cgroup = Path("/sys/fs/cgroup") / relative.lstrip("/")
            assert current["Id"] in str(cgroup)
            memory = {"peak_bytes": int((cgroup / "memory.peak").read_text()),
                      "events": {key: int(value) for key, value in
                                 (line.split() for line in (cgroup / "memory.events").read_text().splitlines())}}
            assert all(memory["events"].get(key, 0) == 0 for key in ("max", "oom", "oom_kill"))
            return {"service": self.service, "passed": True, "original_container_retained": True,
                    "same_data_volume": True, "absolute_ttl_preserved": True,
                    "orphaned_create_recovered": True, "one_active_writer": True,
                    "memory_after": entry["memory_after"], "image_id": original["Image"],
                    "cap_mib": cap, "memory": memory}
        finally:
            self.cleanup()


def qualify(image_ids: dict[str, str]) -> list[dict]:
    """Caller supplies exact installed Redis image ids; pulls are forbidden."""
    assert set(image_ids) == {"redis-broker", "redis-cache"}
    with tempfile.TemporaryDirectory(prefix="pd-retained-redis-qa-") as directory:
        rows = []
        for service, identifier in image_ids.items():
            # _target requires a digest-pinned Docker reference; local digest
            # resolves to the same supplied image, never tag/latest resolution.
            import subprocess
            metadata = json.loads(subprocess.check_output(["docker", "image", "inspect", identifier], text=True))[0]
            assert metadata["Id"] == identifier
            digest = next(value.split("@", 1)[1] for value in metadata["RepoDigests"] if value.startswith("redis@sha256:"))
            rows.append(RetainedFixture(directory, service, "redis:7-alpine@" + digest).probe_retained())
        return rows
