"""Ordinary synthetic Postgres qualification main; no database or Docker calls."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qa import qualify_postgres_memory as qualifier
from qa.owned_probe_container import OWNER_LABEL


class Cursor:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, parameters=()):
        self.sql, self.parameters = sql, parameters

    def fetchone(self):
        if "current_database(), version()" in self.sql:
            return qualifier.DATABASE, "Synthetic PostgreSQL 16"
        if "current_setting" in self.sql:
            return ("100" if self.parameters == ("max_connections",) else "synthetic",)
        if "pg_stat_activity" in self.sql:
            return (65,)
        if "temp_files" in self.sql:
            return 0, 0
        return (50000,)


class Connection:
    def __init__(self, close_error=None):
        self.close_error = close_error
        self.close_attempts = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return Cursor()

    def close(self):
        self.close_attempts += 1
        if self.close_error:
            raise self.close_error


class InlineExecutor:
    def __init__(self, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def map(self, operation, values):
        return map(operation, values)

    def submit(self, operation, **options):
        future = qualifier.concurrent.futures.Future()
        try:
            future.set_result(operation(**options))
        except BaseException as error:  # noqa: BLE001 - model real executor failure delivery.
            future.set_exception(error)
        return future


class PostgresProbeDocker:
    def __init__(self, close_error=None, body_error=None):
        self.close_error, self.body_error = close_error, body_error
        self.connections = []
        self.running = False
        self.calls = []
        self.run_error = None
        self.connect_error = None
        self.connect_attempts = 0

    def connect(self, **options):
        assert (
            options["host"] == "127.0.0.1" and options["dbname"] == qualifier.DATABASE
        )
        self.connect_attempts += 1
        if self.connect_error and self.connect_attempts == 7:
            raise self.connect_error
        connection = Connection(
            self.close_error if len(self.connections) == 1 else None
        )
        self.connections.append(connection)
        return connection

    def command(self, *args, **_kwargs):
        self.calls.append(args)
        if args[:2] == ("docker", "run"):
            self.name = args[args.index("--name") + 1]
            self.token = args[args.index("--label") + 1].split("=", 1)[1]
            self.running = True
            if self.run_error:
                raise self.run_error
            return "c" * 64
        if args[:3] == ("docker", "image", "inspect"):
            return "sha256:" + "a" * 64
        if args[:2] == ("docker", "inspect"):
            return json.dumps(
                [
                    {
                        "Id": "c" * 64,
                        "Image": "sha256:" + "a" * 64,
                        "Name": "/" + self.name,
                        "Config": {"Labels": {OWNER_LABEL: self.token}},
                        "State": {"Running": self.running},
                        "NetworkSettings": {
                            "Ports": {
                                "5432/tcp": [
                                    {"HostIp": "127.0.0.1", "HostPort": "54328"}
                                ],
                            }
                        },
                    }
                ]
            )
        if args[:2] == ("docker", "exec"):
            if self.body_error:
                raise self.body_error
            return "100\n80\noom 0\noom_kill 0"
        if args[:2] == ("docker", "stop"):
            assert args[-1] == "c" * 64
            self.running = False
            return ""
        raise AssertionError(args)


class PostgresProbeLifetimeTests(unittest.TestCase):
    def invoke(self, root, docker):
        with (
            patch.object(qualifier, "ROOT", root),
            patch.object(qualifier, "command", docker.command),
            patch.object(qualifier.psycopg2, "connect", docker.connect),
            patch.object(
                qualifier.concurrent.futures, "ThreadPoolExecutor", InlineExecutor
            ),
            patch("sys.argv", ["qualify_postgres_memory.py"]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            qualifier.main()

    def test_healthy_main_retains_stopped_fixture_and_existing_measurements(self):
        with tempfile.TemporaryDirectory() as directory:
            docker = PostgresProbeDocker()
            self.invoke(Path(directory), docker)
            self.assertFalse(docker.running)
            self.assertTrue(
                all(item.close_attempts == 1 for item in docker.connections)
            )
            receipt = json.loads(
                next(
                    Path(directory).glob(
                        "outputs/postgres-memory-qualification/*/evidence.json"
                    )
                ).read_text()
            )
            self.assertEqual(
                (receipt["held_sessions"], receipt["simultaneous_queries"]), (65, 64)
            )

    def test_one_connection_close_failure_cannot_skip_other_owned_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            original = RuntimeError("synthetic connection close failure")
            docker = PostgresProbeDocker(close_error=original)
            with self.assertRaises(RuntimeError) as raised:
                self.invoke(Path(directory), docker)
            self.assertIs(raised.exception, original)
            self.assertFalse(docker.running)
            self.assertTrue(
                all(item.close_attempts == 1 for item in docker.connections)
            )

    def test_body_failure_identity_survives_secondary_close_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            original = OSError("synthetic cgroup diagnostic failure")
            docker = PostgresProbeDocker(
                RuntimeError("secondary close failure"), original
            )
            with self.assertRaises(Exception) as raised:
                self.invoke(Path(directory), docker)
            self.assertIs(raised.exception, original)
            self.assertFalse(docker.running)

    def test_interrupted_connection_close_still_attempts_all_other_owned_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            original = KeyboardInterrupt()
            docker = PostgresProbeDocker(close_error=original)
            with self.assertRaises(KeyboardInterrupt) as raised:
                self.invoke(Path(directory), docker)
            self.assertIs(raised.exception, original)
            self.assertFalse(docker.running)
            self.assertTrue(
                all(item.close_attempts == 1 for item in docker.connections)
            )

    def test_lost_created_run_reply_is_drained_only_after_matching_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            original = OSError("synthetic detached command lost reply")
            docker = PostgresProbeDocker()
            docker.run_error = original
            with self.assertRaises(OSError) as raised:
                self.invoke(Path(directory), docker)
            self.assertIs(raised.exception, original)
            self.assertFalse(docker.running)
            self.assertEqual(docker.connections, [])
            receipt = json.loads(
                next(
                    Path(directory).glob(
                        "outputs/postgres-memory-qualification/*/evidence.json"
                    )
                ).read_text()
            )
            self.assertEqual(receipt["status"], "failed")

    def test_partial_parallel_connect_failure_closes_every_created_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            original = OSError("synthetic seventh connection failed")
            docker = PostgresProbeDocker()
            docker.connect_error = original
            with self.assertRaises(OSError) as raised:
                self.invoke(Path(directory), docker)
            self.assertIs(raised.exception, original)
            self.assertFalse(docker.running)
            self.assertGreater(len(docker.connections), 1)
            self.assertTrue(
                all(item.close_attempts == 1 for item in docker.connections)
            )


if __name__ == "__main__":
    unittest.main()
