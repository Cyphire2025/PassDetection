"""Synthetic observer/HTTP fixtures and networkless standalone Python CLI checks."""

import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import workload_capacity_run as workload
from capacity_observer_lifecycle import finish_observer
from run_qualification_stack import ROOT


class Observer:
    def __init__(self):
        self.returncode = None
        self.terminated = 0
        self.killed = 0
        self.waited = 0
        self.done = asyncio.Event()
        self.output = None
        self.waiting = asyncio.Event()

    def terminate(self):
        self.terminated += 1
        self.returncode = -15
        self.done.set()

    def kill(self):
        self.killed += 1
        self.returncode = -9
        self.done.set()

    async def wait(self):
        self.waited += 1
        if self.output is not None:
            assert not self.output.closed
        self.waiting.set()
        await self.done.wait()
        return self.returncode


class WorkloadObserverTests(unittest.IsolatedAsyncioTestCase):
    async def run_to_observer(self, observer, negative):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(workload, "OUTPUT", Path(directory)))
        self.enterContext(patch.object(workload, "inspect_backend", return_value={}))
        self.enterContext(patch.object(workload, "capture_container_events", return_value={}))
        self.enterContext(patch.object(workload, "fixture", return_value={}))
        self.enterContext(patch.object(workload, "synthetic_jpeg", return_value=b"synthetic"))
        self.enterContext(patch.object(workload, "tenant_negatives", side_effect=negative))

        async def spawn(*_args, **kwargs):
            observer.output = kwargs["stdout"]
            return observer

        self.enterContext(
            patch.object(workload.asyncio, "create_subprocess_exec", side_effect=spawn)
        )
        client = AsyncMock()
        client.__aenter__.return_value = client
        self.enterContext(patch.object(workload.httpx, "AsyncClient", return_value=client))
        return asyncio.create_task(workload.main())

    async def test_early_main_failure_reaps_the_owned_observer_before_returning(self):
        observer = Observer()

        async def fail(*_args):
            raise RuntimeError("synthetic tenant-negative failure")

        task = await self.run_to_observer(observer, fail)
        with self.assertRaisesRegex(RuntimeError, "synthetic tenant-negative failure"):
            await task
        self.assertEqual(observer.terminated, 1)
        self.assertEqual(observer.waited, 1)
        self.assertIsNotNone(observer.returncode)
        self.assertTrue(observer.output.closed)

    async def test_main_cancellation_reaps_observer_before_cancellation_propagates(self):
        observer, reached = Observer(), asyncio.Event()

        async def paused(*_args):
            reached.set()
            await asyncio.Event().wait()

        task = await self.run_to_observer(observer, paused)
        await reached.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(observer.terminated, 1)
        self.assertEqual(observer.waited, 1)
        self.assertIsNotNone(observer.returncode)
        self.assertTrue(observer.output.closed)

    async def test_repeated_main_cancellation_keeps_cleanup_alive_until_handle_is_reaped(self):
        observer, reached = Observer(), asyncio.Event()
        observer.terminate = lambda: setattr(observer, "terminated", observer.terminated + 1)

        async def paused(*_args):
            reached.set()
            await asyncio.Event().wait()

        task = await self.run_to_observer(observer, paused)
        await reached.wait()
        task.cancel()
        await observer.waiting.wait()
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        self.assertFalse(observer.output.closed)
        observer.returncode = -15
        observer.done.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual((observer.terminated, observer.waited, observer.killed), (1, 1, 0))
        self.assertTrue(observer.output.closed)


class ObserverCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_finished_observer_is_not_signalled_or_waited_again(self):
        observer = Observer()
        observer.returncode = 0
        await finish_observer(observer)
        self.assertEqual((observer.terminated, observer.waited, observer.killed), (0, 0, 0))

    async def test_termination_race_still_reaps_the_returned_handle(self):
        observer = Observer()

        def raced():
            observer.returncode = 0
            observer.done.set()
            raise ProcessLookupError

        observer.terminate = raced
        await finish_observer(observer)
        self.assertEqual(observer.waited, 1)
        self.assertEqual(observer.killed, 0)

    async def test_unresponsive_observer_is_killed_and_reaped_after_its_stop_deadline(self):
        observer = Observer()
        original = observer.wait

        async def wait():
            if observer.waited == 0:
                observer.waited += 1
                raise TimeoutError
            return await original()

        observer.wait = wait
        await finish_observer(observer)
        self.assertEqual((observer.terminated, observer.waited, observer.killed), (1, 2, 1))
        self.assertEqual(observer.returncode, -9)

    async def test_unreaped_handle_failure_is_not_reported_as_success(self):
        observer = Observer()
        observer.wait = AsyncMock(side_effect=TimeoutError)
        with self.assertRaises(TimeoutError):
            await finish_observer(observer)
        self.assertEqual(observer.killed, 1)


class StandaloneCliTests(unittest.TestCase):
    def test_networkless_help_and_unknown_flag_admission_work_without_backend_pythonpath(self):
        environment = {**os.environ, "PYTHONPATH": "", "PYTHONNOUSERSITE": "1"}
        for name in (
            "APP_SECRET_KEY",
            "POSTGRES_PASSWORD",
            "S3_ACCESS_KEY_ID",
            "S3_SECRET_ACCESS_KEY",
        ):
            environment.pop(name, None)
        with tempfile.TemporaryDirectory() as directory:
            for flag, code in (("--help", 0), ("--url=https://synthetic.invalid", 2)):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/qa/qualify_workload_capacity.py"), flag],
                    cwd=directory,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=20,
                )
                with self.subTest(flag=flag):
                    self.assertEqual(result.returncode, code, result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
            self.assertIn("unrecognized arguments", result.stderr)


if __name__ == "__main__":
    unittest.main()
