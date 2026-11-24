"""Exercise retained build capture with real, bounded synthetic child processes."""

from __future__ import annotations

import asyncio
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mcp_direct_build as target
from bounded_command_output import CommandOutputError, capture_command


class DirectCommandOutputTests(unittest.TestCase):
    def run_child(self, source, *, timeout=5):
        return target.command(sys.executable, "-c", source, timeout=timeout)

    def test_success_preserves_text_mode_newlines_and_discards_unused_stderr(self):
        self.assertEqual(
            self.run_child(
                "import os; os.write(1,b' first\\r\\nsecond\\rlast '); os.write(2,b'private')"
            ),
            "first\nsecond\nlast",
        )

    def test_exact_limit_is_accepted_and_one_extra_byte_fails(self):
        with patch.object(target, "MAX_COMMAND_OUTPUT_BYTES", 127):
            self.assertEqual(
                self.run_child("import os; os.write(1,b'x'*127)"), "x" * 127
            )
            with self.assertRaisesRegex(target.BuildError, "command_output_limit"):
                self.run_child("import os; os.write(1,b'x'*128)")

    def test_unused_stderr_still_consumes_the_combined_budget(self):
        with patch.object(target, "MAX_COMMAND_OUTPUT_BYTES", 127):
            with self.assertRaisesRegex(
                target.BuildError, "command_output_limit"
            ) as raised:
                self.run_child(
                    "import os; os.write(2,b'synthetic-private-diagnostic'*100)"
                )
            self.assertNotIn("synthetic-private-diagnostic", str(raised.exception))

    def test_logs_preserve_stdout_then_stderr_with_one_combined_limit(self):
        source = "import os; os.write(2,b'e'*65); os.write(1,b'o'*62)"

        def redirected(arguments, **kwargs):
            self.assertEqual(arguments, ["docker", "logs", "synthetic-only"])
            return capture_command([sys.executable, "-c", source], **kwargs)

        with patch.object(target, "capture_command", side_effect=redirected):
            with patch.object(target, "MAX_COMMAND_OUTPUT_BYTES", 127):
                self.assertEqual(
                    target.command("docker", "logs", "synthetic-only"),
                    "o" * 62 + "e" * 65,
                )
            with (
                patch.object(target, "MAX_COMMAND_OUTPUT_BYTES", 126),
                self.assertRaisesRegex(target.BuildError, "command_output_limit"),
            ):
                target.command("docker", "logs", "synthetic-only")

    def test_nonzero_and_missing_command_keep_static_private_failures(self):
        with self.assertRaisesRegex(
            target.BuildError, "direct_build_command_failed"
        ) as raised:
            self.run_child("import sys; print('synthetic-private'); sys.exit(7)")
        self.assertNotIn("synthetic-private", str(raised.exception))
        with self.assertRaisesRegex(target.BuildError, "direct_build_command_failed"):
            target.command("synthetic-missing-direct-build-command-937")

    def test_timeout_is_typed_without_command_or_output_diagnostics(self):
        with self.assertRaises(subprocess.TimeoutExpired) as raised:
            self.run_child(
                "import time; print('synthetic-private',flush=True); time.sleep(30)",
                timeout=1,
            )
        self.assertNotIn("synthetic-private", str(raised.exception))
        self.assertIsNone(raised.exception.output)
        self.assertIsNone(raised.exception.stderr)

    def test_separate_sinks_share_budget_and_discard_takes_precedence(self):
        with io.BytesIO() as output, io.BytesIO() as errors:
            capture_command(
                [
                    sys.executable,
                    "-c",
                    "import os; os.write(1,b'out'); os.write(2,b'err'*1000)",
                ],
                timeout=5,
                maximum_bytes=3,
                output=output,
                merge_stderr=False,
                stderr_output=errors,
                discard_stderr=True,
            )
            self.assertEqual(output.getvalue(), b"out")
            self.assertEqual(errors.getvalue(), b"")

    def test_timeout_metadata_distinguishes_missing_executable(self):
        for arguments, timeout, expected in (
            (["synthetic-missing-direct-command-937"], 5, False),
            ([sys.executable, "-c", "import time; time.sleep(30)"], 0.1, True),
        ):
            with self.subTest(expected=expected), io.BytesIO() as output:
                with self.assertRaises(CommandOutputError) as raised:
                    capture_command(
                        arguments, timeout=timeout, maximum_bytes=127, output=output
                    )
                self.assertEqual(raised.exception.timed_out, expected)
                self.assertEqual(raised.exception.reason, "capture_failed_or_timed_out")

    def test_success_overflow_and_timeout_close_and_reap_the_direct_child(self):
        original = asyncio.BaseEventLoop.subprocess_exec
        observed = []

        async def record(loop, *args, **kwargs):
            transport, protocol = await original(loop, *args, **kwargs)
            observed.append(transport)
            return transport, protocol

        for source, error in (
            ("print('ok')", None),
            (
                "import os,time; os.write(2,b'x'*10000); time.sleep(30)",
                target.BuildError,
            ),
            ("import time; time.sleep(30)", subprocess.TimeoutExpired),
        ):
            with (
                self.subTest(error=error),
                patch.object(target, "MAX_COMMAND_OUTPUT_BYTES", 127),
            ):
                with patch.object(asyncio.BaseEventLoop, "subprocess_exec", new=record):
                    if error is None:
                        self.assertEqual(self.run_child(source, timeout=1), "ok")
                    else:
                        with self.assertRaises(error):
                            self.run_child(source, timeout=1)
                transport = observed[-1]
                self.assertIsNotNone(transport.get_returncode())
                self.assertTrue(transport.is_closing())
                for descriptor in (1, 2):
                    self.assertTrue(
                        transport.get_pipe_transport(descriptor).is_closing()
                    )


class DirectExecuteOutputTests(unittest.TestCase):
    def execute(self, source, *, wait=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()

            def run(*args, timeout=60):
                if args[:2] == ("docker", "ps"):
                    return ""
                if args[:2] == ("docker", "info"):
                    return str(16 * target.GIB)
                if args[:2] == ("docker", "start"):
                    return "a" * 64
                if args[:2] == ("docker", "wait"):
                    return (
                        target.command(sys.executable, "-c", source, timeout=1)
                        if wait
                        else "0"
                    )
                if args[:2] == ("docker", "inspect"):
                    return json.dumps({"Running": False, "OOMKilled": False})
                if args[:2] == ("docker", "logs"):
                    return target.command(sys.executable, "-c", source, timeout=timeout)
                raise AssertionError("Unexpected synthetic transport route")

            return target.RetainedBuild(root, root, "e" * 40, run=run).execute(
                "a" * 64, "synthetic", target.GIB
            )

    def test_ordinary_execute_retains_successful_bounded_log(self):
        self.assertEqual(self.execute("print('synthetic-healthy')")["exit_code"], 0)

    def test_ordinary_execute_refuses_oversized_log_without_success_receipt(self):
        with self.assertRaisesRegex(target.BuildError, "command_output_limit"):
            self.execute("import os; os.write(1,b'x'*(16*1024*1024))")

    def test_wait_timeout_preserves_retained_builder_recovery_boundary(self):
        with self.assertRaisesRegex(
            target.BuildError, "builder_still_running_inspect_before_retry"
        ):
            self.execute("import time; time.sleep(30)", wait=True)


if __name__ == "__main__":
    unittest.main()
