"""Apply measured resource limits without discarding persistent or volatile data.

Only the guarded release calls this module. Redis is paused and resized in place;
it is never restarted. PostgreSQL/ClamAV may be recreated against the identical
retained volumes after a verified archive. Checkpoints precede each mutation and
an interrupted operation leaves application writers fenced until explicit retry.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from release_resource_fence import PERSISTENT, mounts
from release_traveller_whatsapp import ReleaseError
from verify_deployment_resource_budget import _memory_bytes

REDIS = ("redis", "redis-broker", "redis-realtime", "redis-cache")
ORDER = (*REDIS, "clamav", "db")
MIB = 1024 * 1024


def environment(container: dict[str, Any]) -> dict[str, str]:
    return dict(value.split("=", 1) for value in container["Config"].get("Env", []) if "=" in value)


def process_identity(container: dict[str, Any]) -> tuple[Any, ...]:
    state = container["State"]
    return (container["Id"], container["Image"], state.get("Pid"), state.get("StartedAt"),
            container.get("RestartCount", 0))


def same_redis_process(current: dict[str, Any], original: dict[str, Any]) -> None:
    if (process_identity(current) != process_identity(original)
            or not current["State"].get("Running") or current["State"].get("OOMKilled")
            or mounts(current) != mounts(original)
            or current["Config"].get("Cmd") != original["Config"].get("Cmd")
            or environment(current) != environment(original)):
        raise ReleaseError("Redis process or data identity changed; never restart or adopt a replacement")


def cgroup_memory(container: dict[str, Any]) -> dict[str, int]:
    """Read the local Linux Docker host's actual cgroup, including file cache.

    This deliberately refuses remote daemons and non-cgroup-v2 hosts rather than
    treating Docker CLI's cache-subtracted display as the hard-limit usage.
    """
    pid = container["State"].get("Pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise ReleaseError("A live Docker process PID is required for memory admission")
    try:
        rows = (Path("/proc") / str(pid) / "cgroup").read_text().splitlines()
        values = [row[3:] for row in rows if row.startswith("0::/")]
        if len(values) != 1 or ".." in Path(values[0]).parts:
            raise ValueError("unverified cgroup-v2 identity")
        root = Path("/sys/fs/cgroup").resolve(strict=True)
        path = (root / values[0].lstrip("/")).resolve(strict=True)
        if path == root or not path.is_relative_to(root) or container["Id"] not in str(path):
            raise ValueError("Docker process does not resolve to its own local cgroup")
        events = dict(line.split() for line in (path / "memory.events").read_text().splitlines())
        return {"current": int((path / "memory.current").read_text()),
                "oom": int(events.get("oom", 0)), "oom_kill": int(events.get("oom_kill", 0))}
    except (OSError, ValueError, KeyError) as error:
        raise ReleaseError("Cannot verify local Docker cgroup memory; resource change refused") from error


def volume_identity(release: Any, name: str) -> dict[str, Any]:
    value = json.loads(release.run("docker", "volume", "inspect", name))[0]
    return {key: value.get(key) for key in ("Name", "Driver", "Mountpoint", "CreatedAt", "Labels", "Options", "Scope")}


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def database_fingerprint(fence: Any) -> dict[str, Any]:
    """Read all application table contents and sequence state without exposing rows."""
    identity = json.loads(fence.sql("SELECT json_build_object('system_identifier', system_identifier::text, "
                                    "'database', current_database(), 'major', current_setting('server_version_num')::int / 10000, "
                                    "'data_directory', current_setting('data_directory')) FROM pg_control_system()"))
    tables = json.loads(fence.sql("SELECT coalesce(json_agg(json_build_array(schemaname, tablename) "
                                  "ORDER BY schemaname, tablename), '[]'::json) FROM pg_tables "
                                  "WHERE schemaname NOT IN ('pg_catalog','information_schema') AND schemaname NOT LIKE 'pg_%'"))
    sequences = json.loads(fence.sql("SELECT coalesce(json_agg(to_json(s) ORDER BY schemaname, sequencename), '[]'::json) "
                                     "FROM pg_sequences s WHERE schemaname NOT IN ('pg_catalog','information_schema') "
                                     "AND schemaname NOT LIKE 'pg_%'"))
    rows = []
    for schema, table in tables:
        qualified = _quote(schema) + "." + _quote(table)
        value = json.loads(fence.sql(
            "SELECT json_build_object('rows', count(*), 'a', coalesce(sum(('x' || substr(md5(row_to_json(t)::text),1,16))::bit(64)::bigint),0), "
            "'b', coalesce(sum(('x' || substr(md5(row_to_json(t)::text),17,16))::bit(64)::bigint),0)) FROM " + qualified + " t"))
        rows.append([schema, table, value])
    for sequence in sequences:
        qualified = _quote(sequence["schemaname"]) + "." + _quote(sequence["sequencename"])
        sequence["state"] = json.loads(fence.sql("SELECT json_build_object('last_value',last_value,'is_called',is_called) FROM " + qualified))
    payload = {"identity": identity, "tables": rows, "sequences": sequences}
    return {"identity": identity, "table_count": len(rows), "sequence_count": len(sequences),
            "sha256": hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


def _target(release: Any, fence: Any, config: dict[str, Any], service: str) -> dict[str, Any]:
    spec = config["services"][service]
    reference = spec.get("image", "")
    if not re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", reference):
        raise ReleaseError(f"{service}: persistent resource image must be digest-pinned")
    image = release.inspect(reference, image=True)
    original = fence.existing(service)
    if not original["State"].get("Running") or original["State"].get("Paused") or original["State"].get("OOMKilled"):
        raise ReleaseError(f"{service}: initial persistent process must be running, unpaused and healthy")
    if original["State"].get("Health", {}).get("Status") != "healthy":
        raise ReleaseError(f"{service}: initial persistent process is not healthy")
    declared = []
    for item in spec.get("volumes", []):
        if item.get("type") != "volume":
            raise ReleaseError(f"{service}: unreviewed persistent mount type")
        logical = item["source"]
        name = config.get("volumes", {}).get(logical, {}).get("name")
        if not name:
            raise ReleaseError(f"{service}: persistent volume must have an explicit resolved name")
        declared.append((name, item["target"], not item.get("read_only", False)))
    current = sorted((item.get("Name"), item.get("Destination"), item.get("RW"))
                     for item in original.get("Mounts", []) if item.get("Type") == "volume")
    temporary = {str(item).split(":", 1)[0] for item in spec.get("tmpfs", [])}
    if any(item.get("Type") != "volume" and not (
            item.get("Type") == "tmpfs" and item.get("Destination") in temporary)
           for item in original.get("Mounts", [])):
        raise ReleaseError(f"{service}: candidate would discard an unreviewed existing mount")
    # Redis image also declares an anonymous /data mount in the nonpersistent
    # domains. It remains attached to the same process; it is never recreated.
    if (service not in REDIS and current != sorted(declared)) or any(item not in current for item in declared):
        raise ReleaseError(f"{service}: candidate would change the existing persistent volume mapping")
    memory = _memory_bytes(spec.get("mem_limit"))
    cpu = int(float(spec.get("cpus", 0)) * 1_000_000_000)
    if memory <= 0 or cpu <= 0:
        raise ReleaseError(f"{service}: explicit positive memory and CPU caps are required")
    command = spec.get("command") or image["Config"].get("Cmd")
    entrypoint = spec.get("entrypoint") or image["Config"].get("Entrypoint")
    if service in REDIS and (image["Id"] != original["Image"]
                             or command != original["Config"].get("Cmd")
                             or entrypoint != original["Config"].get("Entrypoint")):
        raise ReleaseError(f"{service}: preserving volatile Redis data requires the same image and command")
    if service == "db":
        old_env = environment(original)
        candidate = {**environment(image), **spec.get("environment", {})}
        if any(candidate.get(key) != old_env.get(key) for key in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "PGDATA")):
            raise ReleaseError("PostgreSQL bootstrap identity or PGDATA would change")
        if not reference.startswith("postgres:16-"):
            raise ReleaseError("Only the reviewed PostgreSQL 16 minor-version replacement is supported")
        data = old_env.get("PGDATA", "")
        if len(declared) != 1 or not data or not (data == declared[0][1] or data.startswith(declared[0][1].rstrip("/") + "/")):
            raise ReleaseError("Existing PGDATA is not covered by the identical retained database volume")
    return {"original": original, "image_id": image["Id"], "reference": reference,
            "memory": memory, "memory_swap": _memory_bytes(spec.get("memswap_limit", memory * 2)),
            "nano_cpus": cpu, "command": command, "entrypoint": entrypoint,
            "volumes": {name: volume_identity(release, name) for name, _, _ in current},
            "stage": "prepared"}


def _verified_backup(release: Any) -> None:
    evidence = release._load_evidence(release.backups_path)
    records = evidence.get("backups")
    if not isinstance(records, list) or not records:
        raise ReleaseError("Persistent maintenance requires an independently verified database archive")
    release._validate_backup_record(records[-1])


def _save(fence: Any, record: dict[str, Any], service: str, stage: str) -> None:
    record["persistent"][service]["stage"] = stage
    fence.save(record)


def _resize_redis(release: Any, fence: Any, record: dict[str, Any], service: str) -> None:
    entry = record["persistent"][service]
    original = entry["original"]
    current = fence.existing(service)
    same_redis_process(current, original)
    if entry["stage"] == "complete":
        if (current["State"].get("Paused") or current["HostConfig"].get("Memory") != entry["memory"]
                or current["HostConfig"].get("MemorySwap") != entry["memory"]
                or current["HostConfig"].get("NanoCpus") != entry["nano_cpus"]
                or cgroup_memory(current)["oom_kill"] != entry["memory_before"]["oom_kill"]):
            raise ReleaseError(f"{service}: completed resource state has changed")
        return
    _save(fence, record, service, "pausing")
    try:
        if not current["State"].get("Paused"):
            release.run("docker", "pause", original["Id"])
        current = release.inspect(original["Id"])
        same_redis_process(current, original)
        if not current["State"].get("Paused"):
            raise ReleaseError("Redis did not pause; memory resize refused")
        before = cgroup_memory(current)
        if before["current"] + max(32 * MIB, entry["memory"] // 5) > entry["memory"]:
            raise ReleaseError(f"{service}: current memory lacks the required safe resize headroom")
        entry["memory_before"] = before
        _save(fence, record, service, "resizing")
        release.run("docker", "update", "--memory", str(entry["memory"]), "--memory-swap", str(entry["memory"]),
                    "--cpus", str(entry["nano_cpus"] / 1_000_000_000), original["Id"])
        current = release.inspect(original["Id"])
        same_redis_process(current, original)
        host = current["HostConfig"]
        after = cgroup_memory(current)
        if (host.get("Memory") != entry["memory"] or host.get("MemorySwap") != entry["memory"]
                or host.get("NanoCpus") != entry["nano_cpus"]
                or after["oom"] != before["oom"] or after["oom_kill"] != before["oom_kill"]):
            raise ReleaseError(f"{service}: memory resize did not preserve the verified process")
        _save(fence, record, service, "resized")
    finally:
        # Even a failed Docker update must not strand the identical Redis process
        # paused. Never start/restart an absent, replaced, or OOM-killed process.
        current = release.inspect(original["Id"])
        same_redis_process(current, original)
        if current["State"].get("Paused"):
            release.run("docker", "unpause", original["Id"])
    current = release.inspect(original["Id"])
    same_redis_process(current, original)
    after = cgroup_memory(current)
    if current["State"].get("Paused") or after["oom_kill"] != entry["memory_before"]["oom_kill"]:
        raise ReleaseError(f"{service}: process did not resume without OOM")
    entry["memory_after"] = after
    _save(fence, record, service, "complete")


def _current_optional(release: Any, fence: Any, service: str) -> dict[str, Any] | None:
    identifiers = release.run("docker", "ps", "--all", "--quiet", "--filter",
                              f"label=com.docker.compose.project={release.compose[3]}", "--filter",
                              f"label=com.docker.compose.service={service}").split()
    return fence.existing(service) if identifiers else None


def _verify_replacement(release: Any, fence: Any, entry: dict[str, Any], service: str, *, compare_data: bool = True) -> None:
    current = fence.existing(service)
    if (current["Image"] != entry["image_id"] or not current["State"].get("Running")
            or current["State"].get("OOMKilled") or current["State"].get("Health", {}).get("Status") != "healthy"
            or current["Config"].get("Cmd") != entry["command"]
            or current["Config"].get("Entrypoint") != entry["entrypoint"]
            or current["HostConfig"].get("Memory") != entry["memory"]
            or current["HostConfig"].get("MemorySwap") != entry["memory_swap"]
            or current["HostConfig"].get("NanoCpus") != entry["nano_cpus"]):
        raise ReleaseError(f"{service}: candidate process or resource verification failed")
    original_volumes = [item for item in mounts(entry["original"]) if item["Type"] == "volume"]
    current_volumes = [item for item in mounts(current) if item["Type"] == "volume"]
    if current_volumes != original_volumes:
        raise ReleaseError(f"{service}: persistent volume identity changed")
    if service == "db":
        if compare_data:
            if database_fingerprint(fence) != entry["database_before"]:
                raise ReleaseError("Database contents, sequence state or cluster identity changed during resource maintenance")
        else:
            # A later activation retry can follow additive migrations or writes
            # by an already activated new worker. Never compare that legitimate
            # new state with the pre-migration row digest or restore old data.
            identity = json.loads(fence.sql("SELECT json_build_object('system_identifier', system_identifier::text, "
                                           "'database', current_database(), 'major', current_setting('server_version_num')::int / 10000, "
                                           "'data_directory', current_setting('data_directory')) FROM pg_control_system()"))
            if identity != entry["database_before"]["identity"]:
                raise ReleaseError("Database cluster identity changed after resource maintenance")


def _recreate(release: Any, fence: Any, record: dict[str, Any], service: str) -> None:
    entry = record["persistent"][service]
    for name, identity in entry["volumes"].items():
        if volume_identity(release, name) != identity:
            raise ReleaseError(f"{service}: retained volume was replaced or changed")
    if entry["stage"] == "complete":
        _verify_replacement(release, fence, entry, service, compare_data=False)
        return
    current = _current_optional(release, fence, service)
    if entry["stage"] == "prepared" and service == "db":
        if current is None or current["Id"] != entry["original"]["Id"]:
            raise ReleaseError("Database original process disappeared before preservation evidence")
        entry["database_before"] = database_fingerprint(fence)
        if entry["database_before"]["identity"]["major"] != 16:
            raise ReleaseError("Database major-version migration is outside this release")
        if entry["database_before"]["identity"]["data_directory"] != environment(current).get("PGDATA"):
            raise ReleaseError("Effective PostgreSQL data directory differs from the retained PGDATA")
        _save(fence, record, service, "stopping")
    elif entry["stage"] == "prepared":
        _save(fence, record, service, "stopping")
    if current is not None:
        if current["Id"] == entry["original"]["Id"]:
            if current["Image"] != entry["original"]["Image"] or mounts(current) != mounts(entry["original"]):
                raise ReleaseError(f"{service}: original persistent identity changed")
            if current["State"].get("Running"):
                release.run("docker", "stop", "--time", "180", current["Id"], timeout=240)
            stopped = release.inspect(current["Id"])
            # The pinned /init-unprivileged Clam shell exits with SIGTERM's
            # conventional 143. PostgreSQL must itself report clean exit zero.
            allowed_exits = {0, 143} if service == "clamav" else {0}
            if (stopped["State"].get("Running") or stopped["State"].get("OOMKilled")
                    or stopped["State"].get("Error") or stopped["State"].get("ExitCode") not in allowed_exits):
                raise ReleaseError(f"{service}: persistent process did not stop cleanly")
        elif (current["Image"] != entry["image_id"]
              or [item for item in mounts(current) if item["Type"] == "volume"] !=
              [item for item in mounts(entry["original"]) if item["Type"] == "volume"]):
            raise ReleaseError(f"{service}: unknown persistent replacement; maintenance remains fenced")
        elif current["State"].get("Running"):
            # Docker may have completed its replacement before the release
            # process was interrupted. Verify and adopt exactly that candidate;
            # never restart it or double-count an already running process.
            _verify_replacement(release, fence, entry, service)
            _save(fence, record, service, "complete")
            return
    _save(fence, record, service, "starting")
    release.dc("up", "-d", "--no-deps", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "660", service, timeout=720)
    _verify_replacement(release, fence, entry, service)
    _save(fence, record, service, "complete")


def _apply_record(release: Any, fence: Any, record: dict[str, Any]) -> None:
    fence.assert_stopped()
    _verified_backup(release)
    if set(record.get("persistent", {})) != PERSISTENT:
        raise ReleaseError("Persistent resource checkpoint is incomplete")
    for service in ORDER:
        fence.assert_stopped()
        if service in REDIS:
            _resize_redis(release, fence, record, service)
        else:
            _recreate(release, fence, record, service)


def apply_persistent_resources(release: Any, resource_fence: Any, config: dict[str, Any]) -> None:
    resource_fence.assert_stopped()
    resource_fence.verify_binding(config)
    _verified_backup(release)
    record = resource_fence.load()
    if not record or record["phase"] == "complete":
        raise ReleaseError("Persistent resources require the current durable maintenance fence")
    if not record.get("persistent"):
        # Validate every service before mutating the first. Original inspected
        # credentials remain only in the owner-readable release checkpoint.
        record["persistent"] = {name: _target(release, resource_fence, config, name) for name in ORDER}
        resource_fence.save(record)
    _apply_record(release, resource_fence, record)


def recover_persistent_resources(release: Any, resource_fence: Any) -> None:
    record = resource_fence.load()
    if record and record.get("persistent"):
        _apply_record(release, resource_fence, record)
