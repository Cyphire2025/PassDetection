"""Hold the approved two-replica connection envelope against synthetic PostgreSQL.

This measures pool-session arithmetic only, not application throughput or HA.
The database name and loopback target guard prevent accidental production use.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import time
from pathlib import Path

import psycopg2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=55449)
    parser.add_argument("--database", default="passdetection_tooling_capacity")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.database not in {"passdetection_tooling_capacity", "passdetection_ci_capacity"}:
        parser.error("Only the dedicated synthetic capacity databases are allowed")
    options = {"host": "127.0.0.1", "port": args.port, "dbname": args.database,
               "user": os.environ.get("CAPACITY_PG_USER", "postgres"),
               "password": os.environ["CAPACITY_PG_PASSWORD"], "connect_timeout": 10}
    connections = []
    started = time.monotonic()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            futures = [executor.submit(psycopg2.connect, **options,
                application_name="passdetection-capacity-qualification") for _ in range(64)]
            failures = []
            for future in futures:
                try:
                    connections.append(future.result())
                except psycopg2.Error as error:
                    failures.append(error)
            if failures:
                raise RuntimeError("Synthetic pool connections could not all be established") from failures[0]
        with psycopg2.connect(**options) as observer:
            with observer.cursor() as cursor:
                cursor.execute("SHOW max_connections")
                maximum = int(cursor.fetchone()[0])
                cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND application_name = %s",
                               ("passdetection-capacity-qualification",))
                held = cursor.fetchone()[0]
                if maximum != 100 or held != 64:
                    raise RuntimeError("Synthetic PostgreSQL capacity envelope differs from the reviewed case")
            def probe(connection):
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    return cursor.fetchone()[0]
            with concurrent.futures.ThreadPoolExecutor(max_workers=64) as executor:
                if list(executor.map(probe, connections)) != [1] * 64:
                    raise RuntimeError("Concurrent pool session probe failed")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"result": "passed", "scope": "synthetic PostgreSQL concurrent connection envelope",
            "api_replicas": 2, "api_processes_per_replica": 4, "api_pool_per_process": 6,
            "worker_and_beat_connections": 16, "application_connections_held": held,
            "observer_connections": 1, "server_max_connections": maximum,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "throughput_or_failover_proven": False}, indent=2) + "\n")
        return 0
    finally:
        for connection in connections:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
