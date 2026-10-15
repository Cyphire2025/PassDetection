"""Narrow, checkpointed Redis dataset-limit transition under a writer fence.

Only the reviewed broker/cache reductions are allowed. Other command/image
changes still use the generic rejection. A replacement is necessary to persist
startup argv, so every unexpired logical value and absolute TTL is verified and
the original /data volume is explicitly retained (including anonymous cache).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from release_traveller_whatsapp import ReleaseError
from verify_deployment_resource_budget import _memory_bytes

MIB = 1024**2
LIMITS = {"redis-broker": (512 * MIB, 384 * MIB, 896 * MIB),
          "redis-cache": (256 * MIB, 128 * MIB, 192 * MIB)}
MAX_KEYS = 20_000
# Values never leave Redis. Hashes include canonical type/value encoding;
# absolute expiry is tracked separately so legitimate expiry is permitted.
FINGERPRINT_LUA = r"""
local keys=redis.call('KEYS','*')
if #keys > tonumber(ARGV[1]) then return redis.error_reply('key limit exceeded') end
table.sort(keys)
local rows={}
for _,key in ipairs(keys) do
  local kind=redis.call('TYPE',key).ok
  local values={}
  if kind=='string' then values={redis.call('GET',key)}
  elseif kind=='list' then values=redis.call('LRANGE',key,0,-1)
  elseif kind=='set' then values=redis.call('SMEMBERS',key); table.sort(values)
  elseif kind=='zset' then values=redis.call('ZRANGE',key,0,-1,'WITHSCORES')
  elseif kind=='hash' then
    local fields=redis.call('HKEYS',key); table.sort(fields)
    for _,field in ipairs(fields) do table.insert(values,field); table.insert(values,redis.call('HGET',key,field)) end
  else return redis.error_reply('unreviewed Redis value type') end
  local parts={kind}
  for _,value in ipairs(values) do table.insert(parts,tostring(string.len(value))..':'..value) end
  table.insert(rows,{redis.sha1hex(key),redis.sha1hex(table.concat(parts,'|')),redis.call('PEXPIRETIME',key)})
end
local clock=redis.call('TIME')
return cjson.encode({rows=rows,now_ms=tonumber(clock[1])*1000+math.floor(tonumber(clock[2])/1000)})
"""


def reviewed_transition(service: str, old: Any, new: Any, memory: int) -> dict[str, int] | None:
    """Return the one allowed argv delta; never allow arbitrary Redis drift."""
    if service not in LIMITS or not isinstance(old, list) or not isinstance(new, list):
        return None
    old_max, new_max, required_cap = LIMITS[service]
    if memory != required_cap or not old or old[0] != "redis-server" or old.count("--maxmemory") != 1:
        return None
    index = old.index("--maxmemory") + 1
    if index >= len(old) or len(new) != len(old) or new[:index] + new[index + 1:] != old[:index] + old[index + 1:]:
        return None
    if _memory_bytes(old[index]) != old_max or _memory_bytes(new[index]) != new_max:
        return None
    required = {"--maxmemory-policy": "noeviction" if service == "redis-broker" else "allkeys-lru",
                "--appendonly": "yes" if service == "redis-broker" else "no"}
    if service == "redis-broker":
        required["--appendfsync"] = "everysec"
    else:
        required["--save"] = ""
    for option, value in required.items():
        if old.count(option) != 1 or old.index(option) + 1 >= len(old) or old[old.index(option) + 1] != value:
            return None
    if old.count("--requirepass") != 1 or old.index("--requirepass") + 1 >= len(old) or not old[old.index("--requirepass") + 1]:
        return None
    return {"old_maxmemory": old_max, "maxmemory": new_max}


def _cli(release: Any, container: dict, *args: str, database: int = 0) -> str:
    command = container["Config"]["Cmd"]
    password = command[command.index("--requirepass") + 1]
    return release.run("docker", "exec", "-e", "REDISCLI_AUTH=" + password,
                       container["Id"], "redis-cli", "--no-auth-warning", "--raw", "-n", str(database), *args,
                       timeout=90)


def _config(release: Any, container: dict, name: str) -> str:
    lines = _cli(release, container, "CONFIG", "GET", name).splitlines()
    if len(lines) != 2 or lines[0] != name:
        raise ReleaseError("Redis configuration readback was invalid")
    return lines[1]


def fingerprint(release: Any, container: dict) -> dict:
    databases = int(_config(release, container, "databases"))
    if not 1 <= databases <= 16:
        raise ReleaseError("Redis transition supports at most 16 databases")
    rows, now = {}, 0
    for database in range(databases):
        if int(_cli(release, container, "DBSIZE", database=database)) > MAX_KEYS - len(rows):
            raise ReleaseError("Redis transition key inventory exceeds 20000")
        payload = json.loads(_cli(release, container, "EVAL", FINGERPRINT_LUA, "0", str(MAX_KEYS - len(rows)), database=database))
        now = max(now, int(payload["now_ms"]))
        for key_hash, value_hash, expiry in payload["rows"]:
            key = f"{database}:{key_hash}"
            if key in rows or not re.fullmatch(r"[0-9a-f]{40}", key_hash) or not re.fullmatch(r"[0-9a-f]{40}", value_hash):
                raise ReleaseError("Redis transition fingerprint is invalid or ambiguous")
            rows[key] = [value_hash, int(expiry)]
    return {"rows": rows, "now_ms": now, "databases": databases}


def compare_fingerprints(before: dict, after: dict) -> None:
    if before["databases"] != after["databases"]:
        raise ReleaseError("Redis database inventory changed during transition")
    for key, value in after["rows"].items():
        if before["rows"].get(key) != value:
            raise ReleaseError("Redis logical value or absolute TTL changed during transition")
    for key, value in before["rows"].items():
        if key not in after["rows"] and (value[1] < 0 or value[1] > after["now_ms"]):
            raise ReleaseError("Redis transition lost an unexpired key")


def _runtime(release: Any, container: dict, service: str, maximum: int) -> None:
    if (_config(release, container, "maxmemory") != str(maximum)
            or _config(release, container, "maxmemory-policy") != ("noeviction" if service == "redis-broker" else "allkeys-lru")
            or _config(release, container, "appendonly") != ("yes" if service == "redis-broker" else "no")
            or _config(release, container, "dir") != "/data"
            or _config(release, container, "dbfilename") != "dump.rdb"):
        raise ReleaseError("Redis runtime differs from the reviewed dataset transition")
    persistence = dict(line.split(":", 1) for line in _cli(release, container, "INFO", "persistence").splitlines() if ":" in line)
    if persistence.get("rdb_bgsave_in_progress") != "0" or persistence.get("aof_rewrite_in_progress") != "0":
        raise ReleaseError("Redis persistence must be idle before a dataset transition")
    if service == "redis-broker" and (_config(release, container, "appendfsync") != "everysec"
                                      or persistence.get("aof_last_write_status") != "ok"):
        raise ReleaseError("Redis broker AOF persistence is not healthy")


def _snapshot_hash(release: Any, identifier: str, path: str) -> str:
    value = release.run("docker", "exec", identifier, "sha256sum", path).split()[0]
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ReleaseError("Redis snapshot hash is invalid")
    return value


def _retained_override(release: Any, entry: dict, service: str) -> Path:
    """Pin anonymous /data explicitly; never rely on Compose's reuse heuristic."""
    volumes = [item for item in entry["original"]["Mounts"] if item["Type"] == "volume"]
    if len(volumes) != 1 or volumes[0]["Destination"] != "/data" or not volumes[0]["RW"]:
        raise ReleaseError("Redis transition requires exactly the retained writable /data volume")
    name = volumes[0]["Name"]
    alias = "retained_" + service.replace("-", "_")
    path = release.directory / f"{release.revision}.{service}.retained-volume.json"
    value = {"services": {service: {"volumes": [{"type": "volume", "source": alias, "target": "/data"}]}},
             "volumes": {alias: {"external": True, "name": name}}}
    content = json.dumps(value, sort_keys=True, indent=2) + "\n"
    if path.exists():
        if path.is_symlink() or path.read_text() != content:
            raise ReleaseError("Redis retained-volume override differs from its checkpoint")
    else:
        release.write_private(path, content, exclusive=True)
    return path


def transition_dataset(release: Any, fence: Any, record: dict, service: str) -> None:
    # Imported only at runtime to keep generic target validation independent.
    from release_persistent_resources import (
        _save,
        _verify_replacement,
        cgroup_memory,
        environment,
        same_redis_process,
        volume_identity,
    )

    entry = record["persistent"][service]
    original, transition = entry["original"], entry["redis_dataset_transition"]
    fence.assert_stopped()
    for name, identity in entry["volumes"].items():
        if volume_identity(release, name) != identity:
            raise ReleaseError("Redis retained volume identity changed")
    current = fence.existing(service)
    if entry["stage"] == "complete":
        same_redis_process(current, entry["replacement"])
        _verify_replacement(release, fence, entry, service)
        _runtime(release, current, service, transition["maxmemory"])
        return
    if entry["stage"] == "prepared":
        same_redis_process(current, original)
        _runtime(release, current, service, transition["old_maxmemory"])
        used = dict(line.split(":", 1) for line in _cli(release, current, "INFO", "memory").splitlines() if ":" in line)
        if int(used["used_memory"]) + max(8 * MIB, transition["maxmemory"] // 10) > transition["maxmemory"]:
            raise ReleaseError("Redis dataset lacks headroom; refusing eviction or queue loss")
        measured = cgroup_memory(current)
        if measured["current"] + max(32 * MIB, entry["memory"] // 5) > entry["memory"]:
            raise ReleaseError("Redis dataset transition lacks container headroom")
        entry["memory_before"] = measured
        entry["redis_before"] = fingerprint(release, current)
        if not re.fullmatch(r"[0-9a-f]{40}", release.revision):
            raise ReleaseError("Redis archive requires an exact release revision")
        entry["cache_archive"] = f"/data/codex-retained-cache-{release.revision}.rdb"
        if service == "redis-cache":
            # A pre-existing cache snapshot is outside this one-time transition.
            release.run("docker", "exec", current["Id"], "sh", "-c",
                        'test ! -e "$1" && test ! -e "$2"', "--", "/data/dump.rdb", entry["cache_archive"])
        _retained_override(release, entry, service)
        _save(fence, record, service, "redis_snapshotting")
    if entry["stage"] == "redis_snapshotting":
        current = fence.existing(service)
        same_redis_process(current, original)
        compare_fingerprints(entry["redis_before"], fingerprint(release, current))
        if _cli(release, current, "SAVE") != "OK":
            raise ReleaseError("Redis snapshot did not complete")
        entry["redis_snapshot_sha256"] = _snapshot_hash(release, current["Id"], "/data/dump.rdb")
        _save(fence, record, service, "redis_stopping")
    if entry["stage"] == "redis_stopping":
        current = fence.existing(service)
        if current["Id"] != original["Id"]:
            raise ReleaseError("Redis original changed before its recorded clean stop")
        if current["State"].get("Running"):
            same_redis_process(current, original)
            compare_fingerprints(entry["redis_before"], fingerprint(release, current))
            release.run("docker", "stop", "--time", "180", current["Id"], timeout=240)
        stopped = release.inspect(original["Id"])
        if stopped["State"].get("Running") or stopped["State"].get("OOMKilled") or stopped["State"].get("ExitCode") != 0:
            raise ReleaseError("Redis did not stop cleanly; writers remain fenced")
        _save(fence, record, service, "redis_starting")
    if entry["stage"] == "redis_starting":
        current = fence.existing(service)
        if current["Id"] == original["Id"]:
            if current["State"].get("Running"):
                raise ReleaseError("Redis original restarted outside its transition")
            path = _retained_override(release, entry, service)
            release.run(*release.compose, "-f", str(path), "up", "-d", "--no-deps", "--no-build", "--pull", "never",
                        "--wait", "--wait-timeout", "180", service, timeout=240)
        _verify_replacement(release, fence, entry, service)
        current = fence.existing(service)
        if environment(current) != environment(original):
            raise ReleaseError("Redis replacement environment changed")
        _runtime(release, current, service, transition["maxmemory"])
        compare_fingerprints(entry["redis_before"], fingerprint(release, current))
        after = cgroup_memory(current)
        if after["oom"] or after["oom_kill"]:
            raise ReleaseError("Redis replacement encountered memory pressure")
        entry["memory_after"], entry["replacement"] = after, current
        _save(fence, record, service, "redis_verified")
    if entry["stage"] == "redis_verified":
        current = fence.existing(service)
        same_redis_process(current, entry["replacement"])
        if service == "redis-cache":
            # Preserve the one-time file, but do not reload stale cache data on
            # subsequent ordinary restarts. Exact source/destination are owned
            # by this checkpoint; never overwrite an existing archive.
            source = release.run("docker", "exec", current["Id"], "sh", "-c",
                                 'if test -f "$1"; then echo source; elif test -f "$2"; then echo archive; else exit 1; fi',
                                 "--", "/data/dump.rdb", entry["cache_archive"])
            path = "/data/dump.rdb" if source == "source" else entry["cache_archive"]
            if _snapshot_hash(release, current["Id"], path) != entry["redis_snapshot_sha256"]:
                raise ReleaseError("Redis cache transition snapshot changed")
            if source == "source":
                release.run("docker", "exec", current["Id"], "sh", "-c",
                            'test ! -e "$2" && mv "$1" "$2"', "--", "/data/dump.rdb", entry["cache_archive"])
        _save(fence, record, service, "complete")
