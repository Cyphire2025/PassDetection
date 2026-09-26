"""Exercise the real resource transition on disposable, retained synthetic data.

Uses a unique local Compose project; never reads .env or production records.
Only the cgroup transport is adapted for a Windows client: the exact reader runs
in a small read-only Linux host-namespace helper. PostgreSQL, Redis pause/resize,
Compose replacement, volume checks and full row/sequence fingerprints are real.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from release_persistent_resources import (
    ORDER,
    REDIS,
    apply_persistent_resources,
    database_fingerprint,
    recover_persistent_resources,
)
from release_reliability import ReliabilityRelease
from release_resource_fence import ResourceFence
from release_traveller_whatsapp import ReleaseError

PG = "postgres:16-alpine@sha256:e013e867e712fec275706a6c51c966f0bb0c93cfa8f51000f85a15f9865a28cb"
REDIS_IMAGE = "redis:7-alpine@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99"
CLAM = "clamav/clamav:1.5_base@sha256:2a682381f314a3ac6ec13eea55b69bd2594887598e5358d938e711a30df850f2"
PYTHON = "passdetection-phase2-native-final:local"
PASSWORD = "synthetic-release-fixture-only"


class FixtureRelease:
    def __init__(self, directory: Path, project: str, compose_path: Path):
        self.root = ROOT
        self.directory = directory
        self.revision = "a" * 40
        self.previous_schema = "0107_passport_ecr_checks"
        self.backups_path = directory / "backups.json"
        self.compose = ["docker", "compose", "-p", project, "--project-directory", str(ROOT), "-f", str(compose_path)]
        self.activated_services = ("fixture-writer",)
        self.resources = ResourceFence(self)
        self.interrupt_update = True
        self.interrupt_database = True
        self.calls = []

    def run(self, *args, **kwargs):
        self.calls.append(list(args))
        result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False, timeout=kwargs.get("timeout", 900))
        if result.returncode:
            raise RuntimeError(f"Synthetic command failed: {args[:3]}: {result.stderr[-2000:]}")
        if args[:2] == ("docker", "update") and self.interrupt_update:
            self.interrupt_update = False
            raise ReleaseError("INJECTED process failure after actual Redis update")
        return result.stdout.strip()

    def dc(self, *args, **kwargs):
        result = self.run(*self.compose, *args, **kwargs)
        if args[0] == "up" and args[-1] == "db" and self.interrupt_database:
            self.interrupt_database = False
            raise ReleaseError("INJECTED process failure after actual database replacement")
        return result

    def inspect(self, reference, *, image=False):
        return json.loads(self.run("docker", *(["image"] if image else []), "inspect", reference))[0]

    def config_fingerprint(self, config):
        return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()

    def write_private(self, path, text, **kwargs):
        path.write_text(text, encoding="utf-8")

    def _load_evidence(self, path):
        return json.loads(path.read_text())

    _validate_backup_record = ReliabilityRelease._validate_backup_record


def host_memory(release: FixtureRelease, container: dict) -> dict:
    code = "import json,sys; from release_persistent_resources import cgroup_memory; print(json.dumps(cgroup_memory(json.loads(sys.argv[1]))))"
    return json.loads(release.run(
        "docker", "run", "--rm", "--read-only", "--network", "none", "--user", "0",
        "--pid", "host", "--cgroupns", "host", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true", "--memory", "128m", "--memory-swap", "128m", "--cpus", "0.5",
        "--mount", f"type=bind,src={ROOT / 'scripts'},dst=/scripts,readonly",
        "--mount", "type=bind,src=/sys/fs/cgroup,dst=/sys/fs/cgroup,readonly",
        "-e", "PYTHONPATH=/scripts", "--entrypoint", "python", PYTHON, "-c", code, json.dumps(container)))


def main():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    project = "pd-resource-" + stamp
    output = ROOT / "outputs" / "persistent-release-qualification" / stamp
    output.mkdir(parents=True)
    volumes = {name + "-data": {"name": project + "-" + name + "-data"} for name in ORDER}
    services = {}
    for name, maximum, cap in (("redis", 128, 320), ("redis-broker", 512, 1152),
                                ("redis-realtime", 128, 192), ("redis-cache", 256, 320)):
        services[name] = {
            "image": REDIS_IMAGE, "mem_limit": f"{cap + 128}m", "cpus": "0.5",
            "command": ["redis-server", "--requirepass", PASSWORD, "--maxmemory", f"{maximum}mb",
                        "--maxmemory-policy", "allkeys-lru" if name == "redis-cache" else "noeviction",
                        "--save", "", "--appendonly", "yes" if name in {"redis", "redis-broker"} else "no"],
            "volumes": [name + "-data:/data"],
            "healthcheck": {"test": ["CMD", "redis-cli", "-a", PASSWORD, "ping"], "interval": "1s", "timeout": "3s", "retries": 30},
        }
    services["db"] = {
        "image": PG, "mem_limit": "1536m", "cpus": "1.0",
        "environment": {"POSTGRES_DB": "passdetection_ci_resource_fixture", "POSTGRES_USER": "postgres", "POSTGRES_PASSWORD": PASSWORD},
        "command": ["postgres", "-c", "max_connections=100"], "volumes": ["db-data:/var/lib/postgresql/data"],
        "healthcheck": {"test": ["CMD", "pg_isready", "-U", "postgres", "-d", "passdetection_ci_resource_fixture"],
                        "interval": "1s", "timeout": "3s", "retries": 60},
    }
    services["clamav"] = {
        "image": CLAM, "mem_limit": "4096m", "cpus": "2.0", "user": "clamav", "entrypoint": ["/init-unprivileged"],
        "environment": {"CLAMAV_NO_FRESHCLAMD": "true", "CLAMAV_NO_MILTERD": "true", "CLAMD_STARTUP_TIMEOUT": "600"},
        "volumes": ["clamav-data:/var/lib/clamav"], "tmpfs": ["/tmp", "/run", "/var/log/clamav:uid=100,gid=101"],
        "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
        "healthcheck": {"test": ["CMD-SHELL", "echo PING | nc 127.0.0.1 3310 | grep -qx PONG"],
                        "interval": "3s", "timeout": "3s", "retries": 90, "start_period": "60s"},
    }
    services["fixture-writer"] = {
        "image": REDIS_IMAGE, "entrypoint": ["sh", "-c", 'trap "exit 0" TERM; while :; do sleep 1 & wait $!; done'],
        "mem_limit": "32m", "cpus": "0.1",
    }
    compose = {"services": services, "volumes": volumes}
    path = output / "compose.json"
    path.write_text(json.dumps(compose, indent=2))
    release = FixtureRelease(output, project, path)
    receipt = {"status": "failed", "project": project, "production_changes": False}
    try:
        # Copy already-qualified local definitions to a NEW synthetic volume.
        sources = release.run("docker", "ps", "--quiet", "--filter", "label=com.docker.compose.service=clamav").split()
        sources = [identifier for identifier in sources if "qualification" in release.inspect(identifier)["Config"]["Labels"].get("com.docker.compose.project", "")]
        if len(sources) != 1 or release.inspect(sources[0])["Config"]["Image"] != CLAM:
            raise RuntimeError("Exactly one pinned local qualification Clam source is required")
        signatures = output / "signatures"
        signatures.mkdir()
        release.run("docker", "cp", sources[0] + ":/var/lib/clamav/.", str(signatures))
        volume = volumes["clamav-data"]["name"]
        assert volume.startswith(project + "-")
        release.run("docker", "volume", "create", volume)
        release.run("docker", "run", "--rm", "--network", "none", "--user", "0", "--memory", "128m",
                    "--mount", f"type=volume,src={volume},dst=/synthetic",
                    "--mount", f"type=bind,src={signatures},dst=/seed,readonly", "--entrypoint", "sh", CLAM,
                    "-c", "cp -a /seed/. /synthetic/ && chown -R 100:101 /synthetic")
        release.run(*release.compose, "up", "-d", "--wait", "--wait-timeout", "300")
        release.resources.sql("CREATE TABLE public.alembic_version(version_num text PRIMARY KEY); "
                              "INSERT INTO public.alembic_version VALUES ('0107_passport_ecr_checks'); "
                              "CREATE TABLE public.synthetic_records(id bigserial PRIMARY KEY, payload jsonb NOT NULL, secret_text text NOT NULL); "
                              "INSERT INTO public.synthetic_records(payload,secret_text) SELECT jsonb_build_object('n',i),repeat(md5(i::text),8) FROM generate_series(1,500) i; "
                              "CREATE TABLE public.synthetic_child(id bigserial PRIMARY KEY,parent_id bigint REFERENCES public.synthetic_records(id)); "
                              "INSERT INTO public.synthetic_child(parent_id) SELECT id FROM public.synthetic_records")
        for name in REDIS:
            release.dc("exec", "-T", name, "redis-cli", "-a", PASSWORD, "SET", "synthetic-retain", "same-value")
            release.dc("exec", "-T", name, "redis-cli", "-a", PASSWORD, "RPUSH", "synthetic-queue", "one", "two", "three")
            release.dc("exec", "-T", name, "redis-cli", "-a", PASSWORD, "SET", "synthetic-lease", "retained", "EX", "1800")
        before = database_fingerprint(release.resources)
        archive_name = release.revision + "." + "b" * 32 + ".pgdump"
        archive = output / archive_name
        release.dc("exec", "-T", "db", "pg_dump", "-U", "postgres", "-d", "passdetection_ci_resource_fixture", "-Fc", "-f", "/tmp/synthetic.pgdump")
        release.dc("exec", "-T", "db", "pg_restore", "--file=/dev/null", "/tmp/synthetic.pgdump")
        release.run("docker", "cp", release.resources.existing("db")["Id"] + ":/tmp/synthetic.pgdump", str(archive))
        release.backups_path.write_text(json.dumps({"backups": [{"filename": archive_name, "schema": release.previous_schema,
            "validation": "pg_restore_full_archive_decode", "bytes": archive.stat().st_size, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}]}))
        for name, cap in {"redis": 320, "redis-broker": 1152, "redis-realtime": 192, "redis-cache": 320, "db": 1024, "clamav": 3072}.items():
            compose["services"][name]["mem_limit"] = f"{cap}m"
            compose["services"][name]["memswap_limit"] = f"{cap}m"
        path.write_text(json.dumps(compose, indent=2))
        config = json.loads(release.dc("config", "--format", "json"))
        writer = release.resources.existing("fixture-writer")
        record = {"version": 1, "revision": release.revision, "root": str(ROOT), "project": project,
                  "phase": "maintenance", "config_fingerprint": release.config_fingerprint(config),
                  "writers": {"fixture-writer": writer}, "persistent": {}, "automatic_rollback_allowed": False}
        release.resources.save(record)
        release.run("docker", "stop", "--time", "20", writer["Id"])
        interruptions = []
        with patch("release_persistent_resources.cgroup_memory", side_effect=lambda item: host_memory(release, item)):
            for attempt in range(3):
                try:
                    if attempt == 0:
                        apply_persistent_resources(release, release.resources, config)
                    else:
                        # Read the durable checkpoint afresh on every retry.
                        release.resources = ResourceFence(release)
                        recover_persistent_resources(release, release.resources)
                    break
                except ReleaseError as error:
                    if not str(error).startswith("INJECTED"):
                        raise
                    interruptions.append(str(error))
            assert len(interruptions) == 2
            after = database_fingerprint(release.resources)
            assert after == before
            redis_states = {}
            checkpoint = release.resources.load()
            for name in REDIS:
                current = release.resources.existing(name)
                old = checkpoint["persistent"][name]["original"]
                assert current["Id"] == old["Id"] and current["State"]["Pid"] == old["State"]["Pid"]
                assert release.dc("exec", "-T", name, "redis-cli", "-a", PASSWORD, "GET", "synthetic-retain") == "same-value"
                assert release.dc("exec", "-T", name, "redis-cli", "-a", PASSWORD, "LRANGE", "synthetic-queue", "0", "-1").splitlines() == ["one", "two", "three"]
                assert int(release.dc("exec", "-T", name, "redis-cli", "-a", PASSWORD, "TTL", "synthetic-lease")) > 0
                redis_states[name] = {"same_container_and_process": True, "keys_queue_lease_retained": True,
                                       "memory": host_memory(release, current), "cap": current["HostConfig"]["Memory"]}
            receipt.update(status="passed", database_before=before, database_after=after,
                           redis=redis_states, interruption_recovery=interruptions,
                           all_persistent_stages_complete=all(entry["stage"] == "complete" for entry in checkpoint["persistent"].values()),
                           archive_fully_decoded=True, volumes_and_database_retained=True,
                           limitations=["Synthetic local fixtures, not a production disaster-recovery exercise",
                                        "Existing-instance PostgreSQL16 minor replacement mechanics exercised; source and target fixture use same pinned16.14 image",
                                        "Real application queue drain separately tested; this fixture has an inert writer",
                                        "Stopped synthetic containers, volumes and archives retained"])
    finally:
        release.run(*release.compose, "stop", "--timeout", "60")
        (output / "evidence.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps({"status": receipt["status"], "evidence": str(output / "evidence.json")}), flush=True)


if __name__ == "__main__":
    main()
