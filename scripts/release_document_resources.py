"""Exact retained-container RAM transition for the document distribution release.

Qualification is an attempt-local, image/source-bound receipt. Nothing in this
module upgrades the candidate profile's qualification status. Original Redis
containers are retained, stopped, and never mounted concurrently with replacements.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

from mcp_direct_build import command
from mcp_direct_containers import clone_payload
from mcp_direct_release import bound_original
from mcp_direct_state import private_json
from release_persistent_resources import volume_identity
from release_redis_dataset_transition import reviewed_transition, transition_dataset
from release_retained_update import require

MIB = 1024**2
LIMITS = {"worker": (384, 1024), "frontend": (512, 256),
          "redis-broker": (1152, 896), "redis-cache": (320, 192)}
DATASETS = {"redis-broker": 384, "redis-cache": 128}
PROFILE = "tooling/deployment-profiles/kvm4.json"
OVERLAY = "docker-compose.kvm4.yml"
RECEIPT = "document-resource-qualification.json"
CHECKS = {"sender_bounded_batches": True, "frontend_pressure": True,
          "redis_dataset_preservation": True, "redis_aof_rewrite": True, "oom_free": True}
QUALIFIED_SOURCES = (
    "scripts/release_document_resources.py", "scripts/release_document_resource_binding.py",
    "scripts/release_document_retained_update.py", "scripts/release_document_distribution_policy.py",
    "scripts/release_document_fast.py", "scripts/qa/qualify_document_migration.py",
    "scripts/release_document_distribution_contract.py", "scripts/release_resource_profile.py",
    "scripts/release_redis_dataset_transition.py", "scripts/release_persistent_resources.py",
    "scripts/release_retained_update.py", "scripts/release_companies_runtime.py",
    "scripts/mcp_direct_containers.py", "scripts/mcp_direct_release.py",
    "scripts/qa/qualify_document_release_resources.py", "scripts/qa/probe_document_sender.py",
    "scripts/qa/qualify_retained_redis_transition.py",
    "scripts/qa/qualify_document_delivery_rebalance.py", "scripts/qa/qualify_redis_dataset_transition.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def qualified_source_hashes(root: Path) -> dict[str, str]:
    return {name: sha256(root / name) for name in QUALIFIED_SOURCES}


def ensure_qualification(release) -> None:
    """Only fresh preparation may run provider-free, isolated image probes."""
    path = release.directory / RECEIPT
    if path.exists() or path.is_symlink():
        qualification(release)
        return
    require("resource_qualification" not in release.record and "candidates" not in release.record
            and "database_backup" not in release.record, "resource_qualification_missing_on_resume")
    live, images = release.record["live"], release.record["image_ids"]
    # The producer refuses a dirty source, wrong image labels, insufficient
    # available host RAM or any nonzero cgroup pressure/OOM counter. No live
    # credentials, data volumes, network endpoints or providers are passed.
    command(sys.executable, "-B", str(release.source / "scripts/qa/qualify_document_release_resources.py"),
            "--revision", release.revision, "--backend-image", images["backend"],
            "--frontend-image", images["frontend"], "--broker-image", live["redis-broker"]["Image"],
            "--cache-image", live["redis-cache"]["Image"], "--postgres-image", live["db"]["Image"],
            "--output", str(path), timeout=1800)
    qualification(release)


def qualification(release) -> dict:
    path = release.directory / RECEIPT
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 65536,
            "exact_image_resource_qualification_required")
    if os.name == "posix":
        require(path.stat().st_uid == os.geteuid() and not path.stat().st_mode & 0o077,
                "resource_qualification_custody_invalid")
    raw = path.read_bytes()
    value = json.loads(raw)
    live = release.record["live"]
    expected = {"version": 1, "kind": "document_distribution_resources_v1", "qualified": True,
                "revision": release.revision,
                "image_ids": {**release.record["image_ids"],
                              **{name: live[name]["Image"] for name in DATASETS}},
                "profile_sha256": sha256(release.source / PROFILE),
                "overlay_sha256": sha256(release.source / OVERLAY),
                "source_sha256": qualified_source_hashes(release.source),
                "limits_mib": {name: pair[1] for name, pair in LIMITS.items()},
                "redis_maxmemory_mib": DATASETS, "host_reserve_mib": 2048,
                "provider_calls": 0, "checks": CHECKS}
    require(isinstance(value, dict) and set(value) == {*expected, "evidence_sha256"}
            and json.dumps({key: value.get(key) for key in expected}, sort_keys=True)
            == json.dumps(expected, sort_keys=True),
            "resource_qualification_binding_changed")
    evidence = value["evidence_sha256"]
    require(isinstance(evidence, dict) and bool(evidence) and len(evidence) <= 32
            and all(isinstance(name, str) and re.fullmatch(r"[a-z0-9_-]{1,100}", name)
                    and isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest)
                    for name, digest in evidence.items()), "resource_evidence_digests_required")
    result = {"sha256": hashlib.sha256(raw).hexdigest(), "binding": expected}
    previous = release.record.get("resource_qualification")
    require(previous is None or previous == result, "resource_qualification_changed_on_resume")
    return result


def require_budget(release, *, source_limits: bool) -> None:
    metadata = json.loads((release.source / PROFILE).read_text())
    limits = metadata["memory_limits_mib"]
    require(set(limits) == set(release.record["live"]) and metadata["host_reserve_mib"] == 2048
            and sum(limits.values()) == metadata["steady_container_ceiling_mib"] == 13888,
            "document_resource_profile_inventory_changed")
    for name, row in release.record["live"].items():
        expected = LIMITS[name][0] if source_limits and name in LIMITS else limits[name]
        require(type(row["HostConfig"].get("Memory")) is int
                and row["HostConfig"]["Memory"] == expected * MIB,
                "inspected_resource_profile_changed")
        if name in LIMITS:
            require(limits[name] == LIMITS[name][1]
                    and row["HostConfig"].get("MemorySwap") == expected * MIB,
                    "reviewed_resource_delta_changed")
    require((13888 + 2048) * MIB <= int(command("docker", "info", "--format", "{{.MemTotal}}")),
            "steady_capacity_exceeds_host_reserve")
    require(not Path("/proc/swaps").read_text().splitlines()[1:], "swap_must_remain_disabled")


def create_app_candidate(release, original: dict, options: dict) -> str:
    payload = clone_payload(original, **options)
    service = original["Config"]["Labels"]["com.docker.compose.service"]
    if service in {"worker", "frontend"}:
        old, new = LIMITS[service]
        require(payload["HostConfig"]["Memory"] == old * MIB
                and payload["HostConfig"]["MemorySwap"] == old * MIB,
                "application_resource_baseline_changed")
        payload["HostConfig"].update(Memory=new * MIB, MemorySwap=new * MIB)
    return release.client.identifier(release.client.request(
        "POST", "/containers/create?" + urlencode({"name": options["name"]}), payload)["Id"])


def redis_payload(release, service: str, entry: dict) -> dict:
    """Clone only the reviewed Redis identity, volume, argv and resource delta."""
    old = entry["original"]
    host, config = copy.deepcopy(old["HostConfig"]), copy.deepcopy(old["Config"])
    require(service in DATASETS and reviewed_transition(service, config["Cmd"], entry["command"], entry["memory"]),
            "unreviewed_redis_resource_change")
    require(host.get("Privileged") is False and not host.get("AutoRemove") and not host.get("PortBindings")
            and not host.get("VolumesFrom") and host.get("NetworkMode") in old["NetworkSettings"]["Networks"],
            "redis_launch_policy_changed")
    volumes = old["Mounts"]
    require(len(volumes) == 1 and volumes[0]["Type"] == "volume"
            and volumes[0]["Destination"] == "/data" and volumes[0]["RW"], "exact_redis_data_volume_required")
    name = release.project + "-" + service
    config.update(Image=old["Image"], Cmd=entry["command"], Hostname=name)
    config["Labels"] = {**config.get("Labels", {}), "com.docker.compose.project": release.project,
                        "com.docker.compose.project.working_dir": str(release.source),
                        "com.docker.compose.oneoff": "False", "globalconnects.retained_original": old["Id"]}
    config["Labels"].pop("com.docker.compose.project.config_files", None)
    host.update(Memory=entry["memory"], MemorySwap=entry["memory"],
                Binds=[volumes[0]["Name"] + ":/data:rw"], Mounts=[])
    endpoints = {}
    for network, endpoint in old["NetworkSettings"]["Networks"].items():
        aliases = endpoint.get("Aliases") or []
        require(service in aliases, "redis_service_alias_required")
        # Preserve legacy service DNS without giving a new process an old
        # container's unique name or id. The original is stopped before create.
        aliases = sorted({value for value in aliases if value not in
                          {old["Id"], old["Id"][:12], old.get("Name", "").lstrip("/")}} | {name})
        endpoints[network] = {"NetworkID": endpoint["NetworkID"], "Aliases": aliases}
    return {**config, "HostConfig": host, "NetworkingConfig": {"EndpointsConfig": endpoints}}


class RetainedRedis:
    def __init__(self, release):
        self.release = release
        self.directory, self.revision = release.directory, release.revision

    def run(self, *args, **kwargs):
        if args[:2] == ("docker", "stop"):
            # Retained lifecycle never escalates a timed-out graceful shutdown.
            identifier = args[-1]
            self.release.client.request("POST", f"/containers/{identifier}/kill?signal=TERM")
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                if not self.inspect(identifier)["State"]["Running"]:
                    return identifier
                time.sleep(0.25)
            raise ValueError("redis_still_draining_no_force_stop")
        return command(*args, **kwargs)

    def inspect(self, identifier):
        return self.release.client.inspect(identifier)

    @staticmethod
    def write_private(path, content, *, exclusive):
        require(exclusive, "exclusive_retained_resource_file_required")
        private_json(path, json.loads(content))

    def save(self, record):
        self.release.event("redis-resource-checkpoint", persistent=record["persistent"])

    def assert_stopped(self):
        self.release.assert_writer_fence()

    def existing(self, service):
        entry = self.release.record["persistent"][service]
        original = entry.get("retained_candidate") or entry["original"]
        return bound_original(original)

    def current_redis(self, service):
        return self.existing(service)

    def replace_redis(self, service, entry):
        self.assert_stopped()
        require(not bound_original(entry["original"])["State"]["Running"], "redis_original_still_running")
        payload = redis_payload(self.release, service, entry)
        name = self.release.project + "-" + service
        if "retained_candidate" not in entry:
            # Name is a durable create intent: recover an interrupted create
            # only after checking the entire expected immutable payload below.
            matches = [row for row in self.release.rows(all=True) if row.get("Name", "").lstrip("/") == name]
            require(len(matches) <= 1, "ambiguous_retained_redis_candidate")
            if matches:
                row = matches[0]
                require(not row["State"]["Running"], "unrecorded_redis_candidate_running")
                from release_document_resource_binding import verify_payload
                verify_payload(row, payload)
            else:
                identifier = self.release.client.request("POST", "/containers/create?" + urlencode({"name": name}), payload)["Id"]
                row = self.inspect(identifier)
            entry["retained_candidate"] = row
            self.save(self.release.record)
        current = bound_original(entry["retained_candidate"])
        if not current["State"]["Running"]:
            self.release.client.request("POST", f"/containers/{current['Id']}/start")
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            current = bound_original(entry["retained_candidate"])
            require(not current["State"].get("OOMKilled"), "redis_candidate_oom")
            if current["State"].get("Health", {}).get("Status") == "healthy":
                return
            time.sleep(1)
        raise ValueError("redis_candidate_health_timeout")


def prepare(release) -> None:
    require_budget(release, source_limits=True)
    receipt = qualification(release)
    adapter = RetainedRedis(release)
    persistent = {}
    for service, maximum in DATASETS.items():
        old = bound_original(release.record["live"][service])
        require(old["State"]["Running"] and old["State"].get("Health", {}).get("Status") == "healthy",
                "healthy_redis_resource_source_required")
        argv = list(old["Config"]["Cmd"])
        require(argv.count("--maxmemory") == 1, "redis_dataset_baseline_changed")
        argv[argv.index("--maxmemory") + 1] = str(maximum * MIB)
        transition = reviewed_transition(service, old["Config"]["Cmd"], argv, LIMITS[service][1] * MIB)
        require(transition is not None, "redis_dataset_baseline_changed")
        entry = {"original": old, "image_id": old["Image"], "memory": LIMITS[service][1] * MIB,
                 "memory_swap": LIMITS[service][1] * MIB, "nano_cpus": old["HostConfig"]["NanoCpus"],
                 "command": argv, "entrypoint": old["Config"].get("Entrypoint"),
                 "redis_dataset_transition": transition, "stage": "prepared"}
        redis_payload(release, service, entry)
        entry["volumes"] = {item["Name"]: volume_identity(adapter, item["Name"]) for item in old["Mounts"]}
        persistent[service] = entry
    release.event("document-resources-prepared", resource_qualification=receipt, persistent=persistent)


def apply(release) -> None:
    require(qualification(release) == release.record.get("resource_qualification"),
            "retained_resource_qualification_required")
    validation = release.record.get("database_validation")
    require(isinstance(validation, dict), "verified_database_migration_required")
    require(validation.get("target_schema") == release.candidate_schema and release.schema() == release.candidate_schema
            and validation.get("image_id") == release.record["image_ids"]["backend"]
            and validation.get("backup_sha256") == release.record.get("database_backup", {}).get("sha256")
            and validation.get("baseline_sha256") == release.record.get("source_preservation_baseline", {}).get("preservation_sha256"),
            "resource_migration_receipt_binding_changed")
    adapter = RetainedRedis(release)
    for service in DATASETS:
        transition_dataset(adapter, adapter, release.record, service)


def infrastructure(release) -> dict:
    from mcp_direct_state import INFRASTRUCTURE
    result = {name: release.record["live"][name] for name in INFRASTRUCTURE}
    for name, entry in release.record.get("persistent", {}).items():
        if "retained_candidate" in entry:
            result[name] = entry["retained_candidate"]
    return result
