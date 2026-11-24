"""Actual local process controls for retained migration machine-stream ownership."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import release_companies_runtime as runtime
from bounded_command_output import CommandOutputError, capture_command


class MigrationOutputDeadlineTests(unittest.TestCase):
    def process(self, script):
        original = capture_command

        def launch(arguments, **kwargs):
            self.assertEqual(arguments, ["docker", "logs", "synthetic-helper-id"])
            self.assertFalse(kwargs["merge_stderr"])
            self.assertTrue(kwargs["discard_stderr"])
            return original([sys.executable, "-B", "-c", script], **kwargs)

        return patch("release_companies_runtime.capture_command", side_effect=launch)

    def launch_error(self):
        return patch.object(
            asyncio.BaseEventLoop,
            "subprocess_exec",
            side_effect=OSError("synthetic-private-launch-detail"),
        )

    def test_exited_command_cannot_admit_stdout_held_by_descendant_past_deadline(self):
        script = (
            "import subprocess,sys;"
            "subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(1.5)'],"
            "stdin=subprocess.DEVNULL);"
            "print('synthetic-reference-only-receipt',flush=True)"
        )
        started = time.monotonic()
        with (
            self.process(script),
            self.assertRaisesRegex(ValueError, "^migration_result_read_failed$"),
        ):
            runtime.migration_stdout("synthetic-helper-id", timeout=0.4)
        self.assertLess(time.monotonic() - started, 1.25)

    def test_discarded_stderr_does_not_consume_stdout_budget_or_change_raw_bytes(self):
        expected = b"\xff\r\nsynthetic\rdata\n"
        script = (
            "import sys;sys.stderr.buffer.write(b's'*131072);sys.stderr.flush();"
            f"sys.stdout.buffer.write({expected!r});sys.stdout.flush()"
        )
        with self.process(script):
            self.assertEqual(runtime.migration_stdout("synthetic-helper-id"), expected)

    def test_launch_failure_remains_static_and_private(self):
        with self.launch_error(), self.assertRaises(ValueError) as caught:
            runtime.migration_stdout("synthetic-helper-id")
        self.assertEqual(str(caught.exception), "migration_result_read_failed")
        self.assertNotIn("synthetic-private-launch-detail", str(caught.exception))

    def test_output_sink_failure_is_distinct_from_output_limit(self):
        class UnwritableOutput:
            def write(self, data: bytes) -> int:
                raise OSError("synthetic-private-write-detail")

        with self.assertRaises(CommandOutputError) as caught:
            capture_command(
                [sys.executable, "-B", "-c", "print('synthetic')"],
                timeout=5,
                maximum_bytes=32768,
                output=UnwritableOutput(),
                discard_stderr=True,
                stdin=subprocess.DEVNULL,
            )
        self.assertEqual(caught.exception.reason, "output_limit_or_capture_failed")
        self.assertFalse(caught.exception.output_limit)
        self.assertNotIn("synthetic-private-write-detail", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
