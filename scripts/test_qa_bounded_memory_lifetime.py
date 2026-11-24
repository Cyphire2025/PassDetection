"""Actual runner/orchestrator entry points with synthetic container/process state."""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from qa import qualify_bounded_memory as qualifier
from qa.owned_probe_container import OWNER_LABEL

IMAGE = "sha256:" + "a" * 64
CONTAINER = "c" * 64


class BoundedProbeDocker:
    def __init__(self, root, error=None):
        self.root, self.error = root, error
        self.running = False
        self.calls = []
        source = root / "scripts/qa/probe_bounded_memory.py"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"synthetic bounded probe source\n")

    def command(self, *args, **_kwargs):
        self.calls.append(args)
        if args[:2] == ("docker", "run"):
            fixture = next(self.root.glob("outputs/memory-qualification/*/fixtures"))
            (fixture / "manifest.json").write_text("{}")
            return ""
        if args[:2] == ("docker", "inspect"):
            return json.dumps(
                [
                    {
                        "Id": CONTAINER,
                        "Image": IMAGE,
                        "Name": "/" + self.name,
                        "Config": {"Labels": {OWNER_LABEL: self.token}},
                        "State": {"Running": self.running, "OOMKilled": False},
                    }
                ]
            )
        if args[:2] == ("docker", "stop"):
            assert args[-1] == CONTAINER
            self.running = False
            return ""
        raise AssertionError(args)

    def run(self, arguments, **_kwargs):
        self.calls.append(tuple(arguments))
        self.name = arguments[arguments.index("--name") + 1]
        self.token = arguments[arguments.index("--label") + 1].split("=", 1)[1]
        self.running = True
        if self.error:
            raise self.error
        self.running = False
        return subprocess.CompletedProcess(
            arguments, 0, stdout=json.dumps({"mode": "baseline"})
        )


class BoundedRunnerLifetimeTests(unittest.TestCase):
    def invoke(self, root, docker):
        with (
            patch.object(qualifier, "ROOT", root),
            patch.object(qualifier, "command", docker.command),
            patch.object(qualifier.subprocess, "run", docker.run),
            patch(
                "sys.argv",
                ["qualify_bounded_memory.py", "--image", IMAGE, "--modes", "baseline"],
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            qualifier.main()

    def test_healthy_exited_probe_is_retained_with_its_original_workload_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docker = BoundedProbeDocker(root)
            self.invoke(root, docker)
            receipt = json.loads(
                next(
                    root.glob("outputs/memory-qualification/*/evidence.json")
                ).read_text()
            )
            self.assertEqual(receipt["workloads"][0]["returncode"], 0)
            self.assertFalse(receipt["workloads"][0]["oom_killed"])
            self.assertFalse(docker.running)

    def test_driver_timeout_or_cancellation_finishes_only_its_owned_probe(self):
        for error in (
            subprocess.TimeoutExpired("synthetic docker run", 180),
            KeyboardInterrupt(),
        ):
            with (
                self.subTest(error=type(error).__name__),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                docker = BoundedProbeDocker(root, error)
                with self.assertRaises(type(error)) as raised:
                    self.invoke(root, docker)
                self.assertIs(raised.exception, error)
                self.assertFalse(docker.running)
                self.assertTrue(
                    list(root.glob("outputs/memory-qualification/*/evidence.json"))
                )


class ProbeProcess:
    def __init__(self, blocked):
        self.blocked = blocked
        self.alive = False
        self.exitcode = None
        self.joins = []
        self.closed = False
        self.join_error = None
        self.start_error = None
        self.terminate_error = None
        self.kills = 0

    def start(self):
        if self.start_error:
            raise self.start_error
        self.alive = self.blocked
        self.exitcode = None if self.blocked else 0

    def join(self, timeout=None):
        self.joins.append(timeout)
        if self.join_error:
            error, self.join_error = self.join_error, None
            raise error

    def is_alive(self):
        return self.alive

    def terminate(self):
        if self.terminate_error:
            raise self.terminate_error
        self.alive, self.exitcode = False, -15

    def kill(self):
        self.kills += 1
        self.alive, self.exitcode = False, -9

    def close(self):
        assert not self.alive
        self.closed = True


class ProbeContext:
    def __init__(self, blocked):
        self.blocked = blocked
        self.processes, self.readers = [], []
        self.configure = lambda _process, _index: None

    def Pipe(self, *, duplex):
        assert duplex is False
        reader = Mock()
        reader.poll.return_value = True
        reader.recv.return_value = {"status": "passed"}
        self.readers.append(reader)
        return reader, Mock()

    def Process(self, *, target, args):
        assert callable(target) and args[0] == "baseline"
        process = ProbeProcess(self.blocked)
        self.configure(process, len(self.processes))
        self.processes.append(process)
        return process


class ProbeChildrenLifetimeTests(unittest.TestCase):
    def invoke(self, context):
        # Windows has no resource/fork module. Exercise the actual owner loop,
        # deliberately substituting native measurements and process protocol.
        with patch.dict(sys.modules, {"resource": SimpleNamespace()}):
            probe = importlib.import_module("qa.probe_bounded_memory")
        celery = SimpleNamespace(loader=SimpleNamespace(import_default_modules=Mock()))
        with (
            patch.dict(
                sys.modules,
                {
                    "app.infrastructure.processing.celery_app": SimpleNamespace(
                        celery_app=celery
                    )
                },
            ),
            patch.dict(
                "os.environ",
                {"APP_ENV": "development", "POSTGRES_DB": "passdetection_ci_memory"},
            ),
            patch.object(probe.multiprocessing, "get_context", return_value=context),
            patch.object(
                probe, "measure", return_value={"synthetic_measurement": True}
            ),
            patch(
                "sys.argv", ["probe_bounded_memory.py", "baseline", "--children", "2"]
            ),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            probe.main()
        return json.loads(output.getvalue())

    def test_healthy_children_keep_original_results_and_exit_code_contract(self):
        context = ProbeContext(False)
        receipt = self.invoke(context)
        self.assertEqual(receipt["exit_codes"], [0, 0])
        self.assertEqual(receipt["results"], [{"status": "passed"}] * 2)
        self.assertTrue(all(process.closed for process in context.processes))

    def test_first_child_timeout_drains_every_created_sibling_and_pipe(self):
        context = ProbeContext(True)
        with self.assertRaisesRegex(RuntimeError, "two minutes"):
            self.invoke(context)
        self.assertEqual(len(context.processes), 2)
        self.assertTrue(all(not process.alive for process in context.processes))
        for reader in context.readers:
            reader.close.assert_called_once()
        self.assertTrue(all(process.closed for process in context.processes))
        self.assertTrue(
            all(
                timeout is not None
                for process in context.processes
                for timeout in process.joins
            )
        )

    def test_cancellation_at_normal_join_drains_all_siblings_without_masking_identity(
        self,
    ):
        context = ProbeContext(True)
        original = KeyboardInterrupt()

        def configure(process, index):
            if index == 0:
                process.join_error = original

        context.configure = configure
        with self.assertRaises(KeyboardInterrupt) as raised:
            self.invoke(context)
        self.assertIs(raised.exception, original)
        self.assertTrue(all(process.closed for process in context.processes))

    def test_partial_start_failure_cleans_prior_child_and_all_created_pipes(self):
        context = ProbeContext(True)
        original = OSError("synthetic second child start failure")

        def configure(process, index):
            if index == 1:
                process.start_error = original

        context.configure = configure
        with self.assertRaises(OSError) as raised:
            self.invoke(context)
        self.assertIs(raised.exception, original)
        self.assertTrue(all(process.closed for process in context.processes))
        for reader in context.readers:
            reader.close.assert_called_once()

    def test_failed_terminate_uses_bounded_kill_without_masking_workload_timeout(self):
        context = ProbeContext(True)

        def configure(process, _index):
            process.terminate_error = KeyboardInterrupt()

        context.configure = configure
        with self.assertRaisesRegex(RuntimeError, "two minutes"):
            self.invoke(context)
        self.assertTrue(
            all(process.closed and process.kills == 1 for process in context.processes)
        )
        self.assertTrue(
            all(
                timeout is not None
                for process in context.processes
                for timeout in process.joins
            )
        )


if __name__ == "__main__":
    unittest.main()
