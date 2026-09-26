"""Durable maintenance fencing; never roll back a database or restart old writers.

The outer release lock serializes operations. Checkpoints survive process death,
bind the exact checkout/project/prepared configuration, and retain original
container and volume identities. A failed upgrade remains stopped for retry.
"""
from __future__ import annotations

import json
import re
from typing import Any

from release_resource_budget import (
    HOST_RESERVE_BYTES,
    MAINTENANCE_SERVICES,
    admit_live_phase,
    plan_release_phases,
)
from release_resource_profile import UNCHANGED_SWAP_SERVICES
from release_traveller_whatsapp import PROJECT_LABEL, SERVICE_LABEL, ReleaseError
from storage_writer_fence import _identity
from verify_deployment_resource_budget import _memory_bytes

PERSISTENT = frozenset({"db", "redis", "redis-broker", "redis-realtime", "redis-cache", "clamav"})
SCHEMA_SQL = "SELECT version_num FROM public.alembic_version"
# Constant-space aggregates rather than a full-table string_agg. The two digest
# halves and row count bind every row without disclosing the rows in the receipt.
ROWS_SQL = r"""SELECT format('SELECT json_build_object(''table'', %L, ''rows'', count(*), ''a'', COALESCE(sum((''x'' || substr(md5(row_to_json(t)::text),1,16))::bit(64)::bigint),0), ''b'', COALESCE(sum((''x'' || substr(md5(row_to_json(t)::text),17,16))::bit(64)::bigint),0)) FROM %I.%I t;', schemaname || '.' || tablename, schemaname, tablename) FROM pg_tables WHERE schemaname='public' ORDER BY tablename;
\gexec
"""


def mounts(container: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(({key: item.get(key) for key in ("Type", "Name", "Source", "Destination", "RW")}
                   for item in container.get("Mounts", [])), key=lambda item: str(item["Destination"]))


class ResourceFence:
    def __init__(self, release: Any) -> None:
        self.release = release
        self.path = release.directory / "resource-maintenance.json"

    def load(self) -> dict[str, Any] | None:
        if self.path.is_symlink():
            raise ReleaseError("Resource checkpoint cannot be a symbolic link")
        if not self.path.exists():
            return None
        record = json.loads(self.path.read_text())
        if (record.get("version") != 1 or record.get("root") != str(self.release.root)
                or re.fullmatch(r"[0-9a-f]{40}", str(record.get("revision", ""))) is None
                or record.get("phase") not in {"fencing", "maintenance", "activating", "complete"}
                or not isinstance(record.get("project"), str) or not record["project"]
                or (record["phase"] != "complete" and record.get("revision") != self.release.revision)):
            raise ReleaseError("Resource checkpoint does not match this checkout/release")
        return record

    def active(self) -> bool:
        record = self.load()
        return bool(record and record["phase"] != "complete")

    def save(self, record: dict[str, Any]) -> None:
        self.release.write_private(self.path, json.dumps(record, indent=2) + "\n")

    @property
    def writers(self) -> set[str]:
        return set(self.release.activated_services)

    def existing(self, service: str) -> dict[str, Any]:
        release = self.release
        ids = release.run("docker", "ps", "--all", "--quiet", "--filter",
                          f"label={PROJECT_LABEL}={release.compose[3]}", "--filter",
                          f"label={SERVICE_LABEL}={service}").split()
        if len(ids) != 1:
            raise ReleaseError(f"{service}: exactly one existing container is required for maintenance")
        container = release.inspect(ids[0])
        _identity(container, service, release.compose[3], release.root)
        return container

    def checked_writer(self, service: str, record: dict[str, Any]) -> dict[str, Any]:
        current = self.existing(service)
        original = record["writers"][service]
        if current["Id"] == original["Id"]:
            if current["Image"] != original["Image"] or mounts(current) != mounts(original):
                raise ReleaseError(f"{service}: original writer image/mount identity changed")
        elif record["phase"] == "activating":
            expected = json.loads(self.release.manifest_path.read_text())["images"][service]
            env = dict(item.split("=", 1) for item in current["Config"].get("Env", []) if "=" in item)
            if (current["Image"] != expected or (service != "frontend" and (
                    env.get("APP_REVISION") != self.release.revision
                    or env.get("EXPECTED_DATABASE_SCHEMA_REVISION") != self.release.expected_schema))):
                raise ReleaseError(f"{service}: replacement is not this prepared release")
        else:
            raise ReleaseError(f"{service}: writer was replaced outside the recorded activation phase")
        return current

    def container(self, service: str) -> dict[str, Any] | None:
        record = self.load()
        if not record or record["phase"] == "complete" or service not in record["writers"]:
            return None
        current = self.checked_writer(service, record)
        # Docker clears live endpoint fields on stop. The immutable original
        # inspected network identity remains the backup-target authority.
        if not current["State"].get("Running") and current["Id"] == record["writers"][service]["Id"]:
            current["NetworkSettings"] = record["writers"][service]["NetworkSettings"]
        elif not current["State"].get("Running"):
            snapshot = record.get("current_writers", {}).get(service)
            if snapshot and snapshot["Id"] == current["Id"] and snapshot["Image"] == current["Image"]:
                current["NetworkSettings"] = snapshot["NetworkSettings"]
        return current

    def plan(self, config: dict[str, Any]) -> dict[str, Any]:
        memory = int(self.release.run("docker", "info", "--format", "{{.MemTotal}}"))
        result = plan_release_phases(config, host_memory_bytes=memory, writers=self.writers)
        if result["errors"]:
            raise ReleaseError("Release memory phases rejected: " + "; ".join(result["errors"]))
        return result

    def verify_binding(self, config: dict[str, Any]) -> None:
        record = self.load()
        if record and record["phase"] != "complete" and (
                record["project"] != self.release.compose[3]
                or record["config_fingerprint"] != self.release.config_fingerprint(config)):
            raise ReleaseError("Prepared configuration changed while maintenance was fenced")

    def assert_stopped(self) -> None:
        record = self.load()
        if not record or record["phase"] == "complete":
            raise ReleaseError("No active resource maintenance checkpoint")
        for service in record["writers"]:
            current = self.checked_writer(service, record)
            if current["State"].get("Running") or current["State"].get("ExitCode") != 0:
                raise ReleaseError(f"{service}: maintenance requires a verified cleanly stopped writer")

    def begin(self, config: dict[str, Any]) -> None:
        release = self.release
        self.verify_binding(config)
        record = self.load()
        if not record or record["phase"] == "complete":
            if record:
                archive = release.directory / f"{record['revision']}.resource-maintenance-complete.json"
                if not archive.exists():
                    release.write_private(archive, json.dumps(record, indent=2) + "\n", exclusive=True)
            original = {service: self.existing(service) for service in sorted(self.writers)}
            if any(not item["State"].get("Running") for item in original.values()):
                raise ReleaseError("Initial maintenance requires all existing writers running and idle")
            record = {"version": 1, "revision": release.revision, "root": str(release.root),
                      "project": release.compose[3], "phase": "fencing",
                      "config_fingerprint": release.config_fingerprint(config), "writers": original,
                      "persistent": {}, "automatic_rollback_allowed": False}
            self.save(record)
        # Stop ingress and producers first. Only then check/drain accepted work.
        for service in ("backend", "email-beat", "frontend"):
            if service in record["writers"]:
                self.stop_writer(service, record)
        worker_states = [self.checked_writer(name, record)["State"].get("Running") for name in release.node_prefixes]
        if any(worker_states):
            release.probe_running_workers_idle()
        elif not record.get("workers_drained"):
            raise ReleaseError("Stopped workers have no durable idle proof")
        record["workers_drained"] = True
        self.save(record)
        for service in release.node_prefixes:
            self.stop_writer(service, record)
        self.assert_stopped()
        if record["phase"] != "activating":
            record["phase"] = "maintenance"
            self.save(record)

    def stop_writer(self, service: str, record: dict[str, Any]) -> None:
        current = self.checked_writer(service, record)
        if current["State"].get("Running"):
            if current["Id"] != record["writers"][service]["Id"]:
                # A partially activated new API must retain its own verified
                # network identity before Docker clears endpoints on stop.
                if service == "backend":
                    self.release._verify_live_database_target(current, self.existing("db"))
                record.setdefault("current_writers", {})[service] = current
                self.save(record)
            self.release.run("docker", "stop", "--time", "180", current["Id"], timeout=240)
        stopped = self.release.inspect(current["Id"])
        if stopped["State"].get("Running") or stopped["State"].get("ExitCode") != 0:
            raise ReleaseError(f"{service}: did not stop cleanly; maintenance remains fenced")

    def admit(self, config: dict[str, Any], services: set[str]) -> None:
        self.assert_stopped()
        ids = self.release.run("docker", "ps", "--quiet").split()
        actual = [self.release.inspect(identifier) for identifier in ids]
        try:
            admit_live_phase(config, host_memory_bytes=int(self.release.run("docker", "info", "--format", "{{.MemTotal}}")),
                             project=self.release.compose[3], running_containers=actual,
                             starting_services=services, required_stopped=self.writers)
        except ValueError as error:
            raise ReleaseError(f"Live release resource budget rejected: {error}") from error

    def sql(self, statement: str) -> str:
        return self.release.dc("exec", "-T", "db", "sh", "-c",
                               'exec psql -X -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"',
                               "release-readonly", statement, timeout=3600)

    def schema(self) -> str:
        value = self.sql(SCHEMA_SQL).strip()
        if not re.fullmatch(r"[0-9]{4}_[A-Za-z0-9_]+", value):
            raise ReleaseError("Could not verify the single existing database revision")
        return value

    def start_activation(self) -> None:
        record = self.load()
        if not record:
            raise ReleaseError("Application activation requires a durable resource fence")
        if record["phase"] != "activating":
            self.assert_stopped()
            record["phase"] = "activating"
            self.save(record)

    def admit_application_start(self, config: dict[str, Any], starting: set[str]) -> None:
        if not starting or not starting <= self.writers:
            raise ReleaseError("Unknown application activation phase")
        total = 0
        for identifier in self.release.run("docker", "ps", "--quiet").split():
            item = self.release.inspect(identifier)
            labels = item.get("Config", {}).get("Labels", {})
            name = labels.get(SERVICE_LABEL)
            if labels.get(PROJECT_LABEL) == self.release.compose[3]:
                if name in MAINTENANCE_SERVICES:
                    raise ReleaseError("A maintenance helper is still running; applications remain fenced")
                if name in starting:
                    # Activation never rolls/replaces a live writer. The outer
                    # fence must stop it and drain its accepted work first.
                    raise ReleaseError(f"{name}: application start requires a stopped existing container")
            total += _memory_bytes(item.get("HostConfig", {}).get("Memory"))
        total += sum(_memory_bytes(config["services"][name].get("mem_limit")) for name in starting)
        host = int(self.release.run("docker", "info", "--format", "{{.MemTotal}}"))
        if total + HOST_RESERVE_BYTES > host:
            raise ReleaseError("Application activation exceeds actual host memory with fixed reserve")

    def complete(self) -> None:
        record = self.load()
        if not record or record["phase"] != "activating":
            raise ReleaseError("Cannot complete an unrecorded activation")
        record["phase"] = "complete"
        self.save(record)

    def verify_actual_limits(self, config: dict[str, Any], *, exact: bool) -> None:
        if exact:
            for name, spec in config["services"].items():
                if name in MAINTENANCE_SERVICES:
                    continue
                item = self.existing(name)
                state, host = item["State"], item["HostConfig"]
                memory = _memory_bytes(spec.get("mem_limit"))
                allowed_swap = {memory, 2 * memory} if name in UNCHANGED_SWAP_SERVICES else {memory}
                if (not state.get("Running") or state.get("Paused") or state.get("OOMKilled")
                        or host.get("Memory") != memory or host.get("MemorySwap") not in allowed_swap
                        or host.get("NanoCpus") != int(float(spec["cpus"]) * 1_000_000_000)):
                    raise ReleaseError(f"{name}: actual process/caps differ from the qualified KVM4 profile")
        total = 0
        for identifier in self.release.run("docker", "ps", "--quiet").split():
            item = self.release.inspect(identifier)
            labels = item.get("Config", {}).get("Labels", {})
            if (labels.get(PROJECT_LABEL) == self.release.compose[3]
                    and labels.get(SERVICE_LABEL) in MAINTENANCE_SERVICES):
                raise ReleaseError("A maintenance helper remains running after application activation")
            total += _memory_bytes(item.get("HostConfig", {}).get("Memory"))
        host_memory = int(self.release.run("docker", "info", "--format", "{{.MemTotal}}"))
        if total + HOST_RESERVE_BYTES > host_memory:
            raise ReleaseError("Final actual container ceilings exceed physical memory with fixed reserve")
