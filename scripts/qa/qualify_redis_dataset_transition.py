"""Run the actual transition against sequential isolated synthetic Redis data.

Use installed images only, network none, 0.5 CPU, at most 1152 MiB, no
production mounts/credentials. Run on the VPS with copied candidate scripts.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from release_persistent_resources import _target
from release_redis_dataset_transition import (
    _cli,
    compare_fingerprints,
    fingerprint,
    transition_dataset,
)
from release_traveller_whatsapp import ReleaseError

LABEL = "passdetection.qa.run"


def guard():
    values = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    available = int(values["MemAvailable"].split()[0]) * 1024
    if available < 6 * 1024**3:
        raise RuntimeError("Host available RAM below 6 GiB; isolated test aborted")
    return round(available / 1024**3, 2)


class Fixture:
    def __init__(self, directory, service, image):
        self.directory = Path(directory)
        self.revision = "a" * 40
        self.service = service
        self.project = "pd-redis-transition-" + uuid.uuid4().hex[:16]
        self.record = {"phase": "maintenance", "persistent": {}}
        self.interrupt_after_start = False
        self.restart_interrupted = False
        self.cleaning = False
        self.compose_path = self.directory / (service + ".json")
        self.compose = ["docker", "compose", "-p", self.project, "--project-directory", str(self.directory), "-f", str(self.compose_path)]
        broker = service == "redis-broker"
        maximum, cap = (512, 1152) if broker else (256, 320)
        command = ["redis-server", "--requirepass", "synthetic-transition-fixture", "--appendonly", "yes" if broker else "no",
                   "--maxmemory", f"{maximum}mb", "--maxmemory-policy", "noeviction" if broker else "allkeys-lru"]
        command += ["--appendfsync", "everysec"] if broker else ["--save", ""]
        self.config = {"services": {service: {"image": image, "user": "redis", "command": command, "network_mode": "none",
            "mem_limit": f"{cap}m", "memswap_limit": f"{cap}m", "cpus": "0.5", "pids_limit": 64,
            "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"], "labels": {LABEL: self.project},
            "volumes": [{"type": "volume", "source": "data", "target": "/data"}],
            "healthcheck": {"test": ["CMD", "redis-cli", "-a", "synthetic-transition-fixture", "ping"],
                            "interval": "1s", "timeout": "2s", "retries": 20}}},
            "volumes": {"data": {"name": self.project + "-data", "labels": {LABEL: self.project}}}}
        self.compose_path.write_text(json.dumps(self.config))

    def run(self, *args, timeout=90, input_text=None, **kwargs):
        if not self.cleaning:
            guard()
        process = subprocess.Popen(args, stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        started = time.monotonic()
        try:
            while True:
                if not self.cleaning:
                    guard()
                if time.monotonic() - started > timeout:
                    raise RuntimeError("Isolated fixture command exceeded its time bound")
                try:
                    stdout, stderr = process.communicate(input=input_text, timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    input_text = None
                    continue
        except BaseException:
            process.kill()
            process.communicate()
            raise
        if process.returncode:
            raise RuntimeError(stderr[-1000:])
        if args[:2] == ("docker", "compose") and "up" in args and args.count("-f") == 2 and self.interrupt_after_start:
            self.interrupt_after_start = False
            self.restart_interrupted = True
            raise ReleaseError("Synthetic interruption immediately after successful replacement")
        return stdout.strip()

    def inspect(self, reference, image=False):
        return json.loads(self.run("docker", *(["image"] if image else []), "inspect", reference))[0]

    def existing(self, service):
        ids = self.run("docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={self.project}",
                       "--filter", f"label=com.docker.compose.service={service}").split()
        if len(ids) != 1:
            raise RuntimeError("Unexpected isolated fixture inventory")
        value = self.inspect(ids[0])
        if value["Config"]["Labels"].get(LABEL) != self.project or value["HostConfig"]["NetworkMode"] != "none":
            raise RuntimeError("Not this fixture's isolated container")
        return value

    def assert_stopped(self):
        # The isolated project's only service is Redis, with no network.
        assert self.record["phase"] == "maintenance"

    def save(self, record):
        self.record = record
        self.write_private(self.directory / (self.service + "-checkpoint.json"), json.dumps(record))

    def write_private(self, path, value, **kwargs):
        Path(path).write_text(value)
        Path(path).chmod(0o600)

    def cleanup(self):
        # Cleanup must still release only our own memory after an admission abort.
        self.cleaning = True
        ids = self.run("docker", "ps", "-aq", "--filter", f"label={LABEL}={self.project}").split()
        for identifier in ids:
            value = self.inspect(identifier)
            assert value["Config"]["Labels"].get(LABEL) == self.project and value["HostConfig"]["NetworkMode"] == "none"
            self.run("docker", "rm", "-f", identifier)
        for volume in self.run("docker", "volume", "ls", "-q", "--filter", f"label={LABEL}={self.project}").split():
            value = json.loads(self.run("docker", "volume", "inspect", volume))[0]
            assert volume == self.project + "-data" and value["Labels"].get(LABEL) == self.project
            self.run("docker", "volume", "rm", volume)

    def probe(self):
        try:
            self.run(*self.compose, "up", "-d", "--pull", "never", "--wait", "--wait-timeout", "45")
            current = self.existing(self.service)
            for command in (("SET", "string", "synthetic"), ("RPUSH", "queue", "one", "two", "three"),
                            ("HSET", "hash", "b", "two", "a", "one"), ("SADD", "set", "b", "a"),
                            ("ZADD", "sorted", "2", "b", "1", "a"), ("SET", "lease", "live", "PX", "900000")):
                _cli(self, current, *command)
            _cli(self, current, "SET", "other-database", "retained", database=1)
            filled_memory = None
            if self.service == "redis-cache":
                cli = ("docker", "exec", "-i", "-e", "REDISCLI_AUTH=synthetic-transition-fixture", current["Id"], "redis-cli")
                self.run(*cli, "-x", "SET", "large-value", input_text="x" * (3 * 1024**2))
                count = 0
                while True:
                    info = dict(line.split(":", 1) for line in _cli(self, current, "INFO", "memory").splitlines() if ":" in line)
                    filled_memory = int(info["used_memory"])
                    if filled_memory >= 128 * 1024**2 * .70:
                        break
                    value = "v" * 32768
                    pipeline = ""
                    for number in range(count, count + 64):
                        key = f"pressure:{number}"
                        pipeline += f"*3\r\n$3\r\nSET\r\n${len(key)}\r\n{key}\r\n${len(value)}\r\n{value}\r\n"
                    output = self.run(*cli, "--pipe", input_text=pipeline)
                    if "errors: 0" not in output:
                        raise RuntimeError("Synthetic pressure fill was incomplete")
                    count += 64
            before = fingerprint(self, current)
            after_fingerprint = dict(line.split(":", 1) for line in _cli(self, current, "INFO", "memory").splitlines() if ":" in line)
            spec = self.config["services"][self.service]
            maximum, cap = (384, 896) if self.service == "redis-broker" else (128, 192)
            spec["command"][spec["command"].index("--maxmemory") + 1] = f"{maximum}mb"
            spec.update(mem_limit=f"{cap}m", memswap_limit=f"{cap}m")
            self.compose_path.write_text(json.dumps(self.config))
            self.record["persistent"][self.service] = _target(self, self, self.config, self.service)
            self.interrupt_after_start = True
            try:
                transition_dataset(self, self, self.record, self.service)
            except ReleaseError as error:
                if not str(error).startswith("Synthetic interruption"):
                    raise
            transition_dataset(self, self, self.record, self.service)
            transition_dataset(self, self, self.record, self.service)
            compare_fingerprints(before, fingerprint(self, self.existing(self.service)))
            entry = self.record["persistent"][self.service]
            running = self.existing(self.service)
            relative = (Path("/proc") / str(running["State"]["Pid"]) / "cgroup").read_text().split("::")[-1].strip()
            cgroup = Path("/sys/fs/cgroup") / relative.lstrip("/")
            assert running["Id"] in str(cgroup)
            peak = int((cgroup / "memory.peak").read_text())
            return {"service": self.service, "passed": entry["stage"] == "complete", "keys": len(before["rows"]),
                    "types": ["string", "list", "hash", "set", "zset"], "databases": 16,
                    "absolute_ttl_preserved": True, "same_data_volume": True,
                    "replacement_interruption_recovered": self.restart_interrupted,
                    "memory_after": entry["memory_after"], "cap_mib": cap,
                    "replacement_peak_mib": round(peak / 1024**2, 2),
                    "cache_fill_used_memory_bytes": filled_memory,
                    "used_memory_after_fingerprint": int(after_fingerprint["used_memory"]),
                    "large_cache_value_bytes": 3 * 1024**2 if self.service == "redis-cache" else None}
        finally:
            self.cleanup()


def main():
    initial = guard()
    installed = json.loads(subprocess.check_output(["docker", "inspect", *subprocess.check_output(
        ["docker", "ps", "-q", "--filter", "label=com.docker.compose.service=redis-broker"], text=True).split()], text=True))[0]
    metadata = json.loads(subprocess.check_output(["docker", "image", "inspect", installed["Image"]], text=True))[0]
    digest = next(value.split("@", 1)[1] for value in metadata["RepoDigests"] if value.startswith("redis@sha256:"))
    image = "redis:7-alpine@" + digest
    with tempfile.TemporaryDirectory(prefix="pd-redis-lifecycle-") as directory:
        rows = [Fixture(directory, service, image).probe() for service in ("redis-broker", "redis-cache")]
    print(json.dumps({"date_utc": datetime.now(UTC).isoformat(), "production_changes": False,
        "initial_host_available_gib": initial, "final_host_available_gib": guard(), "rows": rows,
        "limitations": ["Small synthetic fixtures test preservation and interruption recovery; pressure tested separately.",
                        "Exact final release qualification and guarded idle activation remain pending."]}, indent=2))


if __name__ == "__main__":
    main()
