"""Exact source binding, exclusive storage and privacy bounds for operator collection."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import tempfile
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import mcp_log_collector as collector
from app.core.logging.mcp_log_normalization import COLLECTED_SERVICES
from app.infrastructure.observability.mcp_log_runs import SealedMCPLogReader
from mcp_log_binding import BindingError, DockerBinding
from mcp_log_store import SourceBuffer, admit_output_root, create_run, seal_run
from mcp_log_stream import CommandResult


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root, self.output = self.base / "deployment", self.base / "derived"
        self.root.mkdir()
        self.output.mkdir()
        self.rows = [
            {
                "id": f"{index:064x}",
                "service": service,
                "running": True,
                "started": "2026-09-29T00:00:00Z",
                "image": "sha256:" + "a" * 64,
                "project": "app",
                "root": str(self.root),
                "oneoff": "False",
            }
            for index, service in enumerate(sorted(COLLECTED_SERVICES), 1)
        ]
        self.commands = []
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def metadata(self, arguments, **kwargs):
        self.commands.append(arguments)
        if arguments[1] == "context":
            return b'"unix:///var/run/docker.sock"\n'
        if arguments[1] == "ps":
            rows = self.rows
            services = [
                value.split("=", 2)[2]
                for value in arguments
                if value.startswith("label=com.docker.compose.service=")
            ]
            if services:
                rows = [
                    row
                    for row in rows
                    if row["service"] == services[0]
                    and row["oneoff"] == "False"
                    and row["running"]
                ]
            return ("\n".join(row["id"] for row in rows) + "\n").encode()
        if arguments[1] == "inspect":
            return (
                "\n".join(
                    json.dumps(row) for row in self.rows if row["id"] in arguments[4:]
                )
                + "\n"
            ).encode()
        raise AssertionError(arguments)

    def factory(self, root, project, deadline):
        return DockerBinding(root, project, deadline, metadata=self.metadata)

    def stream(self, arguments, *, consume, **kwargs):
        self.commands.append(arguments)
        self.assertTrue(kwargs["include_stderr"])
        self.assertEqual(arguments[1], "logs")
        self.assertEqual(arguments[-3:-1], ("--tail", "2000"))
        service = next(
            row["service"] for row in self.rows if row["id"] == arguments[-1]
        )
        if service == "nginx":
            line = b'198.51.100.1 - SECRET_USER [29/Sep/2026:12:00:00 +0000] "GET /SECRET_TOKEN HTTP/1.1" 503 20 "-" "SECRET_AGENT" "SECRET_IP" request_id=12345678123412341234123456789012 limit_req_status=PASSED upstream_status=503 request_time=0.5\n'
        else:
            line = (
                json.dumps(
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "event": "frontend_render_failure",
                        "request_id": "12345678123412341234123456789012",
                        "logger": "app.infrastructure.email.client",
                        "message": "SECRET_PASSPORT_AND_TOKEN",
                        "headers": {"Authorization": "SECRET"},
                    }
                )
                + "\n"
            ).encode()
        consume(line)
        return CommandResult(None, len(line), 1, 0)

    def run_collection(self, **kwargs):
        return collector.collect(
            self.root,
            "app",
            self.output,
            docker_factory=self.factory,
            stream=kwargs.pop("stream", self.stream),
            **kwargs,
        )

    def test_bound_collection_persists_only_projection_and_reader_verifies_it(self):
        report = self.run_collection()
        self.assertEqual(
            set(report["sources"]),
            {"api", "worker", "frontend", "integration", "proxy"},
        )
        for entry in report["sources"].values():
            self.assertEqual(entry["status"], "available")
        data = b"".join(
            file.read_bytes() for file in (self.output / report["run_id"]).iterdir()
        )
        self.assertNotIn(b"SECRET", data)
        self.assertNotIn(b"198.51.100.1", data)
        self.assertNotIn(b"app.infrastructure.email.client", data)
        result = asyncio.run(SealedMCPLogReader(self.output).read("api"))
        self.assertTrue(result.available)
        self.assertEqual(
            result.records[0]["request_id"], "12345678-1234-1234-1234-123456789012"
        )
        self.assertEqual(
            {args[1] for args in self.commands}, {"context", "ps", "inspect", "logs"}
        )
        self.assertTrue(
            all(".Config.Env" not in " ".join(args) for args in self.commands)
        )

    def test_replaced_binding_discards_provisional_records(self):
        def restart(arguments, **kwargs):
            result = self.stream(arguments, **kwargs)
            next(row for row in self.rows if row["id"] == arguments[-1])["started"] = (
                "2026-09-29T01:00:00Z"
            )
            return result

        report = self.run_collection(stream=restart)
        self.assertTrue(
            all(
                entry["status"] == "unavailable" and entry["records"] == 0
                for entry in report["sources"].values()
            )
        )
        self.assertTrue(
            all(
                entry["reason"] == "binding_changed"
                for entry in report["sources"].values()
            )
        )

    def test_missing_and_ambiguous_services_explicit_without_arbitrary_selection(self):
        self.rows = [row for row in self.rows if row["service"] != "nginx"]
        backend = copy.deepcopy(
            next(row for row in self.rows if row["service"] == "backend")
        )
        backend["id"] = "f" * 64
        self.rows.append(backend)
        report = self.run_collection()
        self.assertEqual(report["sources"]["api"]["reason"], "source_ambiguous")
        self.assertEqual(report["sources"]["proxy"]["reason"], "source_unavailable")
        self.assertEqual(report["sources"]["integration"]["status"], "partial")

    def test_partial_stream_failure_and_invalid_records_are_not_healthy_empty(self):
        def limited(arguments, **kwargs):
            kwargs["consume"](b"SECRET_UNSTRUCTURED\n")
            return CommandResult("input_limit", 20, 1, 1)

        report = self.run_collection(stream=limited)
        self.assertTrue(
            all(
                entry["status"] == "unavailable" and entry["reason"] == "input_limit"
                for entry in report["sources"].values()
            )
        )

    def test_wrong_project_root_or_running_state_rejected_before_log_read(self):
        for field, value in (
            ("project", "another"),
            ("root", "/other"),
            ("running", False),
        ):
            with self.subTest(field=field):
                old = self.rows[0][field]
                self.rows[0][field] = value
                with self.assertRaisesRegex(BindingError, "binding_changed"):
                    self.factory(self.root, "app", time.monotonic() + 30).discover()
                self.rows[0][field] = old
                self.assertEqual(list(self.output.iterdir()), [])

    def test_remote_docker_and_container_count_are_rejected(self):
        with (
            patch.dict(os.environ, {"DOCKER_HOST": "ssh://SECRET"}),
            self.assertRaisesRegex(BindingError, "remote_docker_forbidden"),
        ):
            self.factory(self.root, "app", time.monotonic() + 30).discover()
        with (
            patch("mcp_log_binding.MAX_CONTAINERS", 2),
            self.assertRaisesRegex(BindingError, "invalid_container_inventory"),
        ):
            self.factory(self.root, "app", time.monotonic() + 30).discover()

    def test_oneoff_does_not_count_as_running_normal_service(self):
        next(row for row in self.rows if row["service"] == "nginx")["oneoff"] = "True"
        self.assertEqual(
            self.run_collection()["sources"]["proxy"]["reason"], "source_unavailable"
        )

    def test_unexpected_probe_errors_never_contain_output(self):
        def broken(*args, **kwargs):
            raise ValueError("SECRET_EXCEPTION")

        binding = DockerBinding(
            self.root, "app", time.monotonic() + 30, metadata=broken
        )
        with self.assertRaisesRegex(BindingError, "^binding_probe_failed$"):
            binding.discover()

    def test_existing_unknown_files_and_exhausted_budget_are_preserved(self):
        sentinel = self.output / "retained.txt"
        sentinel.write_text("unchanged")
        with self.assertRaisesRegex(ValueError, "unsafe_output_root"):
            admit_output_root(self.output)
        self.assertEqual(sentinel.read_text(), "unchanged")
        separate = self.base / "full"
        separate.mkdir()
        run = create_run(separate, "run-20260929T000000Z-" + "a" * 32)
        (run / "api.jsonl").write_bytes(b"existing")
        with (
            patch("mcp_log_store.MAX_ROOT_BYTES", 10),
            self.assertRaisesRegex(ValueError, "output_disk_budget"),
        ):
            admit_output_root(separate)
        self.assertEqual((run / "api.jsonl").read_bytes(), b"existing")

    def test_interrupted_runs_and_existing_bytes_never_overwritten(self):
        run_id = "run-20260929T000000Z-" + "a" * 32
        run = create_run(self.output, run_id)
        (run / "api.jsonl").write_bytes(b"retained")
        with self.assertRaises(FileExistsError):
            seal_run(
                self.output,
                run,
                {},
                {source: SourceBuffer() for source in collector.LOG_SOURCES},
            )
        self.assertFalse((run / "manifest.json").exists())
        self.assertEqual((run / "api.jsonl").read_bytes(), b"retained")
        with self.assertRaisesRegex(ValueError, "output_run_time_collision"):
            create_run(self.output, "run-20260929T000000Z-" + "b" * 32)

    def test_output_record_bounds_produce_explicit_partial(self):
        source = SourceBuffer()
        with patch("mcp_log_store.MAX_SCAN_RECORDS", 1):
            source.add(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "event": "unhandled_exception",
                }
            )
            source.add(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "event": "unhandled_exception",
                }
            )
        data, entry = source.entry("api")
        self.assertEqual(len(data.splitlines()), 1)
        self.assertEqual(entry["status"], "partial")
        self.assertEqual(entry["reason"], "output_limit")

    def test_writer_independently_reprojects_and_rejects_nonallowlisted_failure(self):
        source = SourceBuffer()
        source.add(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "event": "unhandled_exception",
                "message": "SECRET",
                "password": "SECRET",
            }
        )
        self.assertNotIn(b"SECRET", source.entry("api")[0])
        source.failure = "SECRET_EXCEPTION"
        with self.assertRaisesRegex(ValueError, "^invalid_source_state$"):
            source.entry("api")

    def test_new_concurrent_replica_makes_previously_unique_binding_unavailable(self):
        def replacement(arguments, **kwargs):
            result = self.stream(arguments, **kwargs)
            if (
                next(row["service"] for row in self.rows if row["id"] == arguments[-1])
                == "backend"
            ):
                clone = copy.deepcopy(
                    next(row for row in self.rows if row["id"] == arguments[-1])
                )
                clone["id"] = "f" * 64
                self.rows.append(clone)
            return result

        self.assertEqual(
            self.run_collection(stream=replacement)["sources"]["api"]["reason"],
            "binding_changed",
        )

    def test_failed_new_binding_leaves_retained_incomplete_run(self):
        self.rows[0]["project"] = "wrong"
        with self.assertRaises(BindingError):
            self.run_collection()
        runs = list(self.output.iterdir())
        self.assertEqual(len(runs), 1)
        self.assertFalse((runs[0] / "manifest.json").exists())
        result = asyncio.run(SealedMCPLogReader(self.output).read("api"))
        self.assertFalse(result.available)


if __name__ == "__main__":
    unittest.main()
