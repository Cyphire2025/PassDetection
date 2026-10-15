"""Bounded, network-isolated probes of RAM donors using installed VPS images.

No production container, data, mount, configuration, or provider is modified.
Each test container is owned by an exact unique label and removed afterward.
Run on the VPS via SSH stdin; this script requires only Python's stdlib.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

RUN_ID = "document-rebalance-" + uuid.uuid4().hex
LABEL = "passdetection.qa.run"
MIN_AVAILABLE_BYTES = 6 * 1024**3


def command(*arguments: str, data: bytes | None = None, timeout: int = 60) -> str:
    result = subprocess.run(arguments, input=data, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace")[-1200:])
    return result.stdout.decode()


def guard() -> int:
    values = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    available = int(values["MemAvailable"].split()[0]) * 1024
    if available < MIN_AVAILABLE_BYTES:
        raise RuntimeError("Host available RAM fell below the 6 GiB guard; aborting isolated probe")
    return available


def inspect(name: str) -> dict:
    return json.loads(command("docker", "inspect", name))[0]


def memory(name: str) -> dict:
    state = inspect(name)
    if not state["State"]["Running"]:
        return {"running": False, "oom_killed": state["State"]["OOMKilled"]}
    relative = (Path("/proc") / str(state["State"]["Pid"]) / "cgroup").read_text().split("::")[-1].strip()
    root = Path("/sys/fs/cgroup") / relative.lstrip("/")
    return {"running": True, "peak_mib": round(int((root / "memory.peak").read_text()) / 1024**2, 2),
        "events": dict(line.split() for line in (root / "memory.events").read_text().splitlines())}


def remove_owned(name: str) -> None:
    identifiers = command("docker", "ps", "-aq", "--filter", f"name=^/{name}$").split()
    if not identifiers:
        return
    if len(identifiers) != 1:
        raise RuntimeError("Ambiguous isolated cleanup target")
    state = inspect(identifiers[0])
    if state["Config"]["Labels"].get(LABEL) != RUN_ID or state["HostConfig"]["NetworkMode"] != "none":
        raise RuntimeError("Cleanup target does not belong to this isolated run")
    command("docker", "rm", "-f", "-v", state["Id"])


def create(name: str, image: str, cap: int, *args: str, user: str | None = None) -> None:
    guard()
    command("docker", "run", "-d", "--name", name, "--label", f"{LABEL}={RUN_ID}",
        "--network", "none", "--cpus", "0.5", "--pids-limit", "64",
        "--memory", f"{cap}m", "--memory-swap", f"{cap}m",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
        *(["--user", user] if user else []), image, *args)


def redis_info(name: str, section: str) -> dict:
    result = command("docker", "exec", name, "redis-cli", "INFO", section)
    return dict(line.split(":", 1) for line in result.splitlines() if ":" in line)


def pipeline(name: str, start: int, count: int, values: list[bytes], *, total: int | None = None) -> None:
    output = bytearray()
    for index in range(start, start + count):
        key = f"probe:{index if total is None else index % total}".encode()
        value = values[index % len(values)]
        output.extend(b"*3\r\n$3\r\nSET\r\n$" + str(len(key)).encode() + b"\r\n" + key + b"\r\n$" + str(len(value)).encode() + b"\r\n" + value + b"\r\n")
    result = command("docker", "exec", "-i", name, "redis-cli", "--pipe", data=bytes(output))
    if "errors: 0" not in result:
        raise RuntimeError("Synthetic Redis writes did not all succeed")


def redis_probe(image: str, *, durable: bool, cap: int, maximum: int) -> dict:
    name = RUN_ID + ("-broker" if durable else "-cache")
    try:
        create(name, image, cap, "redis-server", "--bind", "127.0.0.1", "--save", "",
            "--dir", "/tmp", "--maxmemory", f"{maximum}mb", "--maxmemory-policy",
            "noeviction" if durable else "allkeys-lru", "--appendonly", "yes" if durable else "no",
            "--auto-aof-rewrite-percentage", "0", user="redis")
        values = [os.urandom(32768) for _ in range(64)]
        inserted = 0
        until = time.monotonic() + 120
        while int(redis_info(name, "memory")["used_memory"]) < maximum * 1024**2 * .93:
            guard()
            if time.monotonic() > until:
                raise RuntimeError("Synthetic Redis fill exceeded two minutes")
            pipeline(name, inserted, 64, values)
            inserted += 64
        filled = int(redis_info(name, "memory")["used_memory"])
        overwritten, observed = 0, False
        if durable:
            command("docker", "exec", name, "redis-cli", "BGREWRITEAOF")
            until = time.monotonic() + 120
            while redis_info(name, "persistence")["aof_rewrite_in_progress"] == "1":
                guard()
                if time.monotonic() > until:
                    raise RuntimeError("Synthetic Redis rewrite exceeded two minutes")
                observed = True
                pipeline(name, overwritten, 64, values[1:] + values[:1], total=inserted)
                overwritten += 64
            persistence = redis_info(name, "persistence")
            if not observed or not overwritten or persistence["aof_last_bgrewrite_status"] != "ok":
                raise RuntimeError("Synthetic AOF rewrite was not completed under overlapping writes")
            if redis_info(name, "stats")["evicted_keys"] != "0":
                raise RuntimeError("Durable broker evicted a synthetic key")
        else:
            # Evictable cache must remain healthy after exceeding its key budget.
            for _ in range(24):
                guard()
                pipeline(name, inserted, 64, values)
                inserted += 64
            if int(redis_info(name, "stats")["evicted_keys"]) <= 0:
                raise RuntimeError("Synthetic cache did not exercise eviction")
        measured = memory(name)
        if not measured["running"] or any(measured["events"].get(key) != "0" for key in ("oom", "oom_kill", "max")):
            raise RuntimeError("Synthetic Redis reached its memory limit")
        return {"service": "redis-broker" if durable else "redis-cache", "image": image,
            "cap_mib": cap, "maxmemory_mib": maximum, "filled_used_memory_mib": round(filled / 1024**2, 2),
            "rewrite_observed": observed, "rewrite_overwrites": overwritten, "memory": measured,
            "result": "passed"}
    finally:
        remove_owned(name)


def frontend_probe(image: str) -> dict:
    name = RUN_ID + "-frontend"
    try:
        create(name, image, 256)
        until = time.monotonic() + 45
        while True:
            guard()
            try:
                response = command("docker", "exec", name, "node", "-e",
                    "fetch('http://127.0.0.1:3000/login').then(async r=>{if(!r.ok)process.exit(2);console.log((await r.text()).length)}).catch(()=>process.exit(3))")
                if int(response) > 500:
                    break
            except RuntimeError:
                if time.monotonic() > until:
                    raise
                time.sleep(.5)
        for _ in range(10):
            guard()
            command("docker", "exec", name, "node", "-e",
                "Promise.all(Array.from({length:8},()=>fetch('http://127.0.0.1:3000/login').then(async r=>{if(!r.ok)throw Error();return(await r.text()).length}))).then(x=>console.log(Math.min(...x))).catch(()=>process.exit(2))")
        measured = memory(name)
        if not measured["running"] or any(measured["events"].get(key) != "0" for key in ("oom", "oom_kill", "max")):
            raise RuntimeError("Synthetic frontend reached its memory limit")
        return {"service": "frontend", "image": image, "cap_mib": 256, "requests": 81,
            "concurrency": 8, "memory": measured, "result": "passed"}
    finally:
        remove_owned(name)


def main() -> None:
    initial = guard()
    ids = command("docker", "ps", "-q").split()
    installed = json.loads(command("docker", "inspect", *ids))
    images = {row["Config"]["Labels"].get("com.docker.compose.service"): row["Image"] for row in installed}
    rows = [redis_probe(images["redis-broker"], durable=True, cap=896, maximum=384),
        redis_probe(images["redis-cache"], durable=False, cap=192, maximum=128),
        frontend_probe(images["frontend"])]
    print(json.dumps({"run_id": RUN_ID, "date_utc": datetime.now(timezone.utc).isoformat(),
        "initial_host_available_gib": round(initial / 1024**3, 2), "final_host_available_gib": round(guard() / 1024**3, 2),
        "production_changes": False, "network": "none", "cpu_ceiling_each": .5,
        "containers_sequential": True, "rows": rows,
        "limitations": ["Current installed service images; not a final application release qualification.",
            "Redis fill and rewrite use synthetic keys, not production queues.",
            "Frontend tests public login rendering only, not every authenticated page or a long soak.",
            "Future sustained workload and allocator fragmentation may need larger budgets."]}, indent=2))


if __name__ == "__main__":
    main()
