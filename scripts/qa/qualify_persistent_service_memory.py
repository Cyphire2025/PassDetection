"""Measure isolated Redis fullness/fork and ClamAV reload memory, never production.

Containers and synthetic volumes are retained. Clam signatures are copied from
an explicitly checked local qualification service; its daemon is not reloaded.
These bounded experiments do not establish a universal worst-case memory bound.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import struct
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import redis

ROOT = Path(__file__).resolve().parents[2]
REDIS_IMAGE = "redis:7-alpine@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99"
CLAM_IMAGE = "clamav/clamav:1.5_base@sha256:2a682381f314a3ac6ec13eea55b69bd2594887598e5358d938e711a30df850f2"
PASSWORD = "isolated-synthetic-memory-probe-only"


def command(*args: str) -> str:
    return subprocess.check_output(args, text=True, cwd=ROOT, stderr=subprocess.STDOUT)


def inspect(name: str) -> dict:
    return json.loads(command("docker", "inspect", name))[0]


def cgroup(name: str) -> dict:
    lines = command("docker", "exec", name, "sh", "-c",
                    "cat /sys/fs/cgroup/memory.peak /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.events").splitlines()
    return {"peak_bytes": int(lines[0]), "current_bytes": int(lines[1]),
            "events": dict(line.split() for line in lines[2:])}


def port(name: str, internal: str) -> int:
    bindings = inspect(name)["NetworkSettings"]["Ports"][internal]
    assert len(bindings) == 1 and bindings[0]["HostIp"] == "127.0.0.1"
    return int(bindings[0]["HostPort"])


def redis_probe(run: str, domain: str, maximum_mb: int, cap_mb: int, durable: bool) -> dict:
    name = f"pd-memory-{run}-redis-{domain}"
    args = ["docker", "run", "-d", "--name", name, "--memory", f"{cap_mb}m",
            "--memory-swap", f"{cap_mb}m", "--cpus", "1", "--pids-limit", "64",
            "-p", "127.0.0.1::6379"]
    if durable:
        args += ["--mount", f"type=volume,src={name}-data,dst=/data"]
    args += [REDIS_IMAGE, "redis-server", "--requirepass", PASSWORD,
             "--maxmemory", f"{maximum_mb}mb", "--maxmemory-policy", "allkeys-lru" if domain == "cache" else "noeviction",
             "--save", "", "--appendonly", "yes" if durable else "no"]
    if durable:
        args += ["--appendfsync", "everysec", "--auto-aof-rewrite-percentage", "0"]
    command(*args)
    try:
        client = redis.Redis(host="127.0.0.1", port=port(name, "6379/tcp"), password=PASSWORD,
                             socket_timeout=10, socket_connect_timeout=2)
        deadline = time.monotonic() + 30
        while True:
            try:
                if client.ping():
                    break
            except redis.exceptions.ConnectionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)
        # Incompressible synthetic values make the AOF rewrite substantive.
        values = [os.urandom(32768) for _ in range(64)]
        inserted = 0
        target = maximum_mb * 1024 * 1024 * 0.93
        while client.info("memory")["used_memory"] < target:
            pipe = client.pipeline(transaction=False)
            for _ in range(64):
                pipe.set(f"probe:{inserted}", values[inserted % len(values)])
                inserted += 1
            pipe.execute()
        before = {**client.info("memory"), **client.info("persistence")}
        rewrite_observed = False
        overwritten_during_rewrite = 0
        rewrite_started = None
        if durable:
            client.bgrewriteaof()
            rewrite_started = time.monotonic()
            deadline = rewrite_started + 120
            while time.monotonic() < deadline:
                state = client.info("persistence")
                if not state["aof_rewrite_in_progress"]:
                    break
                rewrite_observed = True
                pipe = client.pipeline(transaction=False)
                for offset in range(64):
                    index = (overwritten_during_rewrite + offset) % inserted
                    pipe.set(f"probe:{index}", values[(index + 1) % len(values)])
                pipe.execute()
                overwritten_during_rewrite += 64
            else:
                raise RuntimeError("Synthetic AOF rewrite did not finish in 120 seconds")
        after = {**client.info("memory"), **client.info("persistence")}
        measured = cgroup(name)
        if durable:
            assert rewrite_observed and overwritten_during_rewrite > 0
            assert after["aof_last_bgrewrite_status"] == "ok"
            assert after["aof_last_write_status"] == "ok"
        assert int(measured["events"]["oom_kill"]) == 0
        return {"domain": domain, "container": name, "image": inspect(name)["Image"],
                "maxmemory_mb": maximum_mb, "container_limit_mb": cap_mb,
                "keys": inserted, "fill_used_memory_bytes": before["used_memory"],
                "aof_rewrite_observed": rewrite_observed, "overwrites_during_rewrite": overwritten_during_rewrite,
                "aof_last_cow_size": after.get("aof_last_cow_size"),
                "rewrite_elapsed_seconds": time.monotonic() - rewrite_started if rewrite_started else None,
                "cgroup": measured,
                "limitations": ["93 percent Redis-accounted fill, not a proof of worst-case allocator fragmentation",
                                "Automatic rewrite scheduling disabled only to explicitly trigger and observe one rewrite",
                                "No production data, authentication or delivery correctness claim"]}
    finally:
        command("docker", "stop", name)


def clamd_request(host_port: int, command_bytes: bytes, payload: bytes | None = None) -> str:
    with socket.create_connection(("127.0.0.1", host_port), timeout=30) as connection:
        connection.sendall(command_bytes)
        if payload is not None:
            connection.sendall(struct.pack("!I", len(payload)) + payload + struct.pack("!I", 0))
        return connection.recv(8192).decode().rstrip("\0\n")


def clam_probe(run: str, source: str, output: Path, cap_mb: int, fixtures: Path | None) -> dict:
    state = inspect(source)
    labels = state["Config"].get("Labels") or {}
    if labels.get("com.docker.compose.service") != "clamav" or "qualification" not in labels.get("com.docker.compose.project", ""):
        raise ValueError("Clam source must be an identified local qualification Compose service")
    if state["Config"]["Image"] != CLAM_IMAGE:
        raise ValueError("Clam source must match the pinned candidate image")
    signatures = output / "signatures"
    signatures.mkdir()
    command("docker", "cp", f"{source}:/var/lib/clamav/.", str(signatures))
    signature_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in signatures.iterdir() if p.is_file()}
    config = output / "clamd.conf"
    config.write_text("Foreground yes\nTCPSocket 3310\nTCPAddr 0.0.0.0\nDatabaseDirectory /var/lib/clamav\nConcurrentDatabaseReload yes\nLogTime yes\nMaxThreads 10\n", encoding="utf-8", newline="\n")
    name = f"pd-memory-{run}-clamav"
    fixture_mount: list[str] = []
    if fixtures is not None:
        fixtures = fixtures.resolve(strict=True)
        fixtures.relative_to((ROOT / "outputs/memory-qualification").resolve(strict=True))
        inventory = json.loads((fixtures / "manifest.json").read_text())
        for filename in ("passport-rgba.png", "email-100-pages.pdf"):
            assert hashlib.sha256((fixtures / filename).read_bytes()).hexdigest() == inventory[filename]["sha256"]
        fixture_mount = ["--mount", f"type=bind,src={fixtures},dst=/fixtures,readonly"]
    command("docker", "run", "-d", "--name", name, "--user", "clamav", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true", "--memory", f"{cap_mb}m", "--memory-swap", f"{cap_mb}m",
            "--cpus", "2", "--pids-limit", "256", "-p", "127.0.0.1::3310",
            "--mount", f"type=bind,src={signatures},dst=/var/lib/clamav,readonly",
            "--mount", f"type=bind,src={config},dst=/qualification-clamd.conf,readonly",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=256m",
            *fixture_mount, "--entrypoint", "clamd", CLAM_IMAGE, "--config-file=/qualification-clamd.conf")
    try:
        host_port = port(name, "3310/tcp")
        deadline = time.monotonic() + 120
        while True:
            try:
                if clamd_request(host_port, b"zPING\0") == "PONG":
                    break
            except (OSError, TimeoutError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.5)
        version = clamd_request(host_port, b"zVERSION\0")
        before = cgroup(name)
        # Harmless official antivirus self-test string; never sent to production.
        eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
        assert clamd_request(host_port, b"zINSTREAM\0", b"synthetic clean document").endswith("OK")
        assert "FOUND" in clamd_request(host_port, b"zINSTREAM\0", eicar)
        # A separately loaded complete engine overlaps the daemon reload. This
        # stresses three engines, beyond sequential updater testing + reload,
        # without claiming to have executed freshclam's own control path.
        extra_engine = None
        scan_results: list[str] = []
        pool = ThreadPoolExecutor(max_workers=10)
        futures = []
        if fixtures is not None:
            extra_engine = subprocess.Popen(["docker", "exec", name, "clamscan", "--no-summary", "/fixtures/email-100-pages.pdf"],
                                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            payloads = [(fixtures / name).read_bytes() for name in ("passport-rgba.png", "email-100-pages.pdf")]
            futures = [pool.submit(clamd_request, host_port, b"zINSTREAM\0", payloads[index % 2]) for index in range(10)]
        started = time.monotonic()
        reload_response = clamd_request(host_port, b"zRELOAD\0")
        assert "RELOADING" in reload_response
        deadline = started + 120
        while time.monotonic() < deadline:
            logs = command("docker", "logs", name)
            if "Database correctly reloaded" in logs:
                break
            if not inspect(name)["State"]["Running"]:
                raise RuntimeError("Synthetic Clam container exited during reload")
            time.sleep(0.5)
        else:
            raise RuntimeError("Clam concurrent reload not verified by daemon log")
        if extra_engine is not None:
            engine_log, _ = extra_engine.communicate(timeout=120)
            (output / "additional-engine.log").write_text(engine_log, encoding="utf-8")
            assert extra_engine.returncode == 0
            scan_results = [future.result(timeout=60) for future in futures]
            assert all(result.endswith("OK") for result in scan_results)
        pool.shutdown(wait=True)
        (output / "clamd.log").write_text(logs, encoding="utf-8")
        assert clamd_request(host_port, b"zINSTREAM\0", b"synthetic clean document").endswith("OK")
        assert "FOUND" in clamd_request(host_port, b"zINSTREAM\0", eicar)
        after = cgroup(name)
        assert int(after["events"]["oom_kill"]) == 0
        return {"container": name, "image": inspect(name)["Image"], "version": version,
                "source_service": source, "signature_sha256": signature_hashes,
                "container_limit_mb": cap_mb, "before_reload": before, "after_reload": after,
                "reload_seconds": time.monotonic() - started,
                "additional_full_engine_loaded": extra_engine is not None,
                "simultaneous_clean_fixture_scans": len(scan_results),
                "clean_and_antivirus_self_test_before_after": "pass",
                "limitations": ["Current feed reload only, not future signature growth or maximum simultaneous scans",
                                "Freshclam download and TestDatabases additional memory not exercised",
                                "Independent daemon; production and shared qualification scanners untouched"]}
    finally:
        command("docker", "stop", name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("redis", "clamav"), required=True)
    parser.add_argument("--clam-source")
    parser.add_argument("--clam-limit-mb", type=int, default=4096)
    parser.add_argument("--scan-fixtures", type=Path)
    args = parser.parse_args()
    if args.mode == "clamav" and not args.clam_source:
        parser.error("Clam mode requires an explicitly guarded qualification source container")
    run = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    output = ROOT / "outputs" / "persistent-memory-qualification" / run
    output.mkdir(parents=True)
    receipt = {"created_utc": datetime.now(timezone.utc).isoformat(), "mode": args.mode, "results": []}
    try:
        if args.mode == "redis":
            for domain, maximum, cap, durable in (("security", 128, 384, True), ("broker", 512, 1536, True),
                                                  ("realtime", 128, 256, False), ("cache", 256, 384, False)):
                result = redis_probe(run, domain, maximum, cap, durable)
                receipt["results"].append(result)
                print(json.dumps(result), flush=True)
        else:
            result = clam_probe(run, args.clam_source, output, args.clam_limit_mb, args.scan_fixtures)
            receipt["results"].append(result)
            print(json.dumps(result), flush=True)
    finally:
        (output / "evidence.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
