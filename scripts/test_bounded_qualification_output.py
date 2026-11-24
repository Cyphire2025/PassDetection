"""Real child-process controls for private, bounded qualification output."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from qa.bounded_qualification_output import capture
from qa.qualify_postgresql_client import QualificationError


class BoundedQualificationOutputTests(unittest.TestCase):
    def test_inherited_pipe_after_parent_exit_obeys_the_command_deadline(self):
        child = (
            "import subprocess,sys; "
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(3)'],"
            "stdin=subprocess.DEVNULL); print('synthetic-parent-finished',flush=True)"
        )
        started = time.monotonic()
        with self.assertRaisesRegex(QualificationError, "timed_out"):
            capture([sys.executable, "-c", child], timeout=1)
        self.assertLess(time.monotonic() - started, 2.5)

    def test_timeout_does_not_wait_for_a_descendant_to_close_stdout(self):
        child = (
            "import subprocess,sys,time; "
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(3)'],"
            "stdin=subprocess.DEVNULL); print('synthetic-private-output',flush=True); "
            "time.sleep(30)"
        )
        started = time.monotonic()
        with self.assertRaisesRegex(QualificationError, "timed_out") as raised:
            capture([sys.executable, "-c", child], timeout=1)
        self.assertNotIn("synthetic-private-output", str(raised.exception))
        self.assertLess(time.monotonic() - started, 2.5)

    def test_exact_budget_retains_combined_bytes_and_replacement_decoding(self):
        child = "import os; os.write(1,b'first\\n'); os.write(2,b'last\\xff')"
        self.assertEqual(capture([sys.executable, "-c", child], timeout=5,
                                 maximum_bytes=11), "first\nlast\ufffd")

    def test_overflow_retains_only_the_private_byte_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            diagnostic = Path(temporary) / "capture.private.log"
            with self.assertRaisesRegex(QualificationError, "output_limit"):
                capture([sys.executable, "-c", "import os; os.write(1,b'x'*100000)"],
                        timeout=5, maximum_bytes=127, diagnostic_path=diagnostic)
            self.assertEqual(diagnostic.read_bytes(), b"x" * 127)

    def test_missing_command_has_a_bounded_private_error(self):
        with self.assertRaisesRegex(QualificationError, "command_failed_or_timed_out") as raised:
            capture(["synthetic-missing-qualification-command-937"], timeout=1)
        self.assertNotIn("synthetic-missing", str(raised.exception))

    def test_success_and_nonzero_processes_preserve_the_existing_error_boundary(self):
        self.assertEqual(capture([sys.executable, "-c", "print('synthetic')"], timeout=5),
                         "synthetic\n" if sys.platform != "win32" else "synthetic\r\n")
        with self.assertRaisesRegex(QualificationError, "helper_failed") as raised:
            capture([sys.executable, "-c", "import sys; sys.stderr.write('private'); sys.exit(7)"],
                    timeout=5)
        self.assertNotIn("private", str(raised.exception))

    def test_real_success_overflow_and_timeout_reap_children_and_close_pipes(self):
        original = asyncio.BaseEventLoop.subprocess_exec
        observed = []

        async def record(loop, *args, **kwargs):
            transport, protocol = await original(loop, *args, **kwargs)
            observed.append(transport)
            return transport, protocol

        for child, maximum, expected in (
            ("print('ok')", 127, None),
            ("import os,time; os.write(1,b'x'*100000); time.sleep(30)", 127, "output_limit"),
            ("import time; time.sleep(30)", 127, "timed_out"),
        ):
            with self.subTest(expected=expected), patch.object(
                asyncio.BaseEventLoop, "subprocess_exec", new=record,
            ):
                if expected is None:
                    capture([sys.executable, "-c", child], timeout=1, maximum_bytes=maximum)
                else:
                    with self.assertRaisesRegex(QualificationError, expected):
                        capture([sys.executable, "-c", child], timeout=1, maximum_bytes=maximum)
                transport = observed[-1]
                self.assertIsNotNone(transport.get_returncode())
                self.assertTrue(transport.is_closing())
                self.assertTrue(transport.get_pipe_transport(1).is_closing())


if __name__ == "__main__":
    unittest.main()
