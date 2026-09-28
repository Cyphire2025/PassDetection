"""Bounded isolated PostgreSQL memory pressure; never connects to production.

Retains its synthetic volume/container and evidence. Holds the declared 64-session
surge envelope and exercises concurrent sorts with PostgreSQL's spill behavior.
This is neither a business throughput claim nor a bound on arbitrary SQL.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "postgres:16-alpine@sha256:e013e867e712fec275706a6c51c966f0bb0c93cfa8f51000f85a15f9865a28cb"
DATABASE = "passdetection_ci_memory"
PASSWORD = "isolated-synthetic-postgres-memory-only"


def command(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True, stderr=subprocess.STDOUT)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-mib", type=int, choices=range(768, 4097), default=1024)
    args = parser.parse_args()
    run = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    name = f"pd-memory-{run}-postgres"
    output = ROOT / "outputs" / "postgres-memory-qualification" / run
    output.mkdir(parents=True)
    command("docker", "run", "-d", "--name", name, "--memory", f"{args.memory_mib}m", "--memory-swap", f"{args.memory_mib}m",
            "--cpus", "1", "--pids-limit", "256", "-p", "127.0.0.1::5432",
            "-e", f"POSTGRES_DB={DATABASE}", "-e", f"POSTGRES_PASSWORD={PASSWORD}",
            "--mount", f"type=volume,src={name}-data,dst=/var/lib/postgresql/data",
            IMAGE, "postgres", "-c", "max_connections=100")
    connections = []
    receipt: dict = {"status": "failed", "container": name, "pinned_image": IMAGE,
                     "memory_cap_mib": args.memory_mib, "production_changes": False}
    try:
        state = json.loads(command("docker", "inspect", name))[0]
        bindings = state["NetworkSettings"]["Ports"]["5432/tcp"]
        assert len(bindings) == 1 and bindings[0]["HostIp"] == "127.0.0.1"
        options = {"host": "127.0.0.1", "port": int(bindings[0]["HostPort"]),
                   "user": "postgres", "password": PASSWORD, "dbname": DATABASE,
                   "connect_timeout": 5, "options": "-c statement_timeout=60000",
                   "application_name": "synthetic-memory-qualification"}
        deadline = time.monotonic() + 90
        while True:
            try:
                observer = psycopg2.connect(**options)
                break
            except psycopg2.OperationalError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Synthetic PostgreSQL did not start") from None
                time.sleep(0.25)
        with observer, observer.cursor() as cursor:
            cursor.execute("SELECT current_database(), version()")
            database, version = cursor.fetchone()
            assert database == DATABASE
            cursor.execute("CREATE TABLE synthetic_roster AS SELECT i AS id, repeat(md5(i::text),4) AS payload FROM generate_series(1,200000) i")
            cursor.execute("ANALYZE synthetic_roster")
            parameters = {}
            for setting in ("max_connections", "shared_buffers", "work_mem", "maintenance_work_mem", "max_parallel_workers_per_gather"):
                cursor.execute("SELECT current_setting(%s)", (setting,))
                parameters[setting] = cursor.fetchone()[0]
            assert parameters["max_connections"] == "100"
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            connections = list(pool.map(lambda _: psycopg2.connect(**options), range(64)))
        started = time.monotonic()

        def sort(connection):
            with connection, connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM (SELECT payload FROM synthetic_roster WHERE id <= 50000 ORDER BY payload DESC) ordered")
                assert cursor.fetchone()[0] == 50000
            return "passed"

        with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
            results = list(pool.map(sort, connections))
        with observer.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE application_name='synthetic-memory-qualification'")
            held = cursor.fetchone()[0]
            cursor.execute("SELECT temp_files,temp_bytes FROM pg_stat_database WHERE datname=current_database()")
            temp_files, temp_bytes = cursor.fetchone()
        assert held == 65 and len(results) == 64
        measurements = command("docker", "exec", name, "sh", "-c",
                               "cat /sys/fs/cgroup/memory.peak /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.events").splitlines()
        events = dict(line.split() for line in measurements[2:])
        assert int(events["oom_kill"]) == 0 and int(events["oom"]) == 0
        receipt.update(status="passed", image_id=state["Image"], version=version,
                       settings=parameters, held_sessions=held, simultaneous_queries=len(results),
                       sort_rows_per_query=50000, synthetic_table_rows=200000,
                       query_elapsed_seconds=time.monotonic() - started,
                       temp_files=temp_files, temp_bytes=temp_bytes,
                       cgroup_peak_bytes=int(measurements[0]), cgroup_current_bytes=int(measurements[1]), cgroup_events=events,
                       limitations=["Synthetic bounded sort pressure, not arbitrary query memory or production throughput",
                                    "No automatic cap approval for other PostgreSQL image digests or connection budgets",
                                    "Stopped synthetic container and volume retained"])
        print(json.dumps(receipt), flush=True)
    finally:
        for connection in connections:
            connection.close()
        if "observer" in locals():
            observer.close()
        command("docker", "stop", "--time", "60", name)
        (output / "evidence.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
