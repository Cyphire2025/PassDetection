"""Real local children cannot overrun the read-only observation byte budget."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp_production_baseline import BaselineError, run

PRODUCER = (
    "import os,pathlib,sys; "
    "os.write(int(sys.argv[1]),b'x'*(9*1024*1024)); "
    "pathlib.Path(sys.argv[2]).write_text('completed',encoding='ascii')"
)


class BaselineOutputTests(unittest.TestCase):
    def test_stdout_limit_interrupts_before_the_whole_producer_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "stdout-completed"
            with self.assertRaisesRegex(BaselineError, "exceeded its output bound"):
                run(sys.executable, "-c", PRODUCER, "1", str(marker))
            self.assertFalse(marker.exists())

    def test_discarded_stderr_still_counts_toward_the_total_byte_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "stderr-completed"
            with self.assertRaisesRegex(BaselineError, "exceeded its output bound"):
                run(sys.executable, "-c", PRODUCER, "2", str(marker))
            self.assertFalse(marker.exists())

    def test_healthy_output_uses_stdout_only_with_universal_newlines_and_strip(self) -> None:
        code = "import os; os.write(1,b' alpha\\r\\nbeta\\rgamma\\n'); os.write(2,b'private-diagnostic')"
        self.assertEqual(run(sys.executable, "-c", code), "alpha\nbeta\ngamma")

    def test_text_decoding_matches_the_existing_subprocess_locale_contract(self) -> None:
        code = "import os; os.write(1,b'locale-byte-\\xff')"
        try:
            expected = subprocess.run(
                [sys.executable, "-c", code], capture_output=True, text=True, check=True,
            ).stdout.strip()
        except UnicodeDecodeError:
            with self.assertRaises(UnicodeDecodeError):
                run(sys.executable, "-c", code)
        else:
            self.assertEqual(run(sys.executable, "-c", code), expected)

    def test_nonzero_output_is_a_static_failure_without_private_bytes(self) -> None:
        with self.assertRaisesRegex(BaselineError, "failed or exceeded") as raised:
            run(sys.executable, "-c", "import sys; print('private-probe'); sys.exit(7)")
        self.assertNotIn("private-probe", str(raised.exception))

    def test_missing_command_has_the_existing_safe_timeout_or_start_failure(self) -> None:
        with self.assertRaisesRegex(BaselineError, "could not finish") as raised:
            run("synthetic-missing-mcp-baseline-command-481")
        self.assertNotIn("synthetic-missing", str(raised.exception))

    def test_stdout_only_capture_reaps_the_child_and_closes_both_pipes(self) -> None:
        original = asyncio.BaseEventLoop.subprocess_exec
        observed: list[asyncio.SubprocessTransport] = []

        async def record(loop, *args, **kwargs):
            transport, protocol = await original(loop, *args, **kwargs)
            observed.append(transport)
            return transport, protocol

        for code, failure in (
            ("print('healthy')", False),
            ("import os; os.write(1,b'x'*(9*1024*1024))", True),
            ("import os; os.write(2,b'x'*(9*1024*1024))", True),
        ):
            with self.subTest(failure=failure), patch.object(
                asyncio.BaseEventLoop, "subprocess_exec", new=record,
            ):
                if failure:
                    with self.assertRaises(BaselineError):
                        run(sys.executable, "-c", code)
                else:
                    self.assertEqual(run(sys.executable, "-c", code), "healthy")
                transport = observed[-1]
                self.assertIsNotNone(transport.get_returncode())
                self.assertTrue(transport.is_closing())
                for descriptor in (1, 2):
                    pipe = transport.get_pipe_transport(descriptor)
                    self.assertIsNotNone(pipe)
                    self.assertTrue(pipe.is_closing())


if __name__ == "__main__":
    unittest.main()
