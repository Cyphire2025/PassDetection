"""Bounded pipe draining terminates only the local child, with no shell invocation."""

from __future__ import annotations

import subprocess
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

from mcp_log_stream import bounded_metadata, stream_command


class StreamTests(unittest.TestCase):
    def drain(self, chunks, **kwargs):
        process = MagicMock()
        process.poll.return_value = None
        process.returncode = 0
        selector = MagicMock()
        selector.__enter__.return_value = selector
        selector.select.return_value = [True]
        output = []
        with (
            patch("mcp_log_stream.subprocess.Popen", return_value=process) as popen,
            patch("mcp_log_stream.os.set_blocking", create=True),
            patch("mcp_log_stream.selectors.DefaultSelector", return_value=selector),
            patch("mcp_log_stream.os.read", side_effect=[*chunks, b""]),
        ):
            result = stream_command(
                ("docker", "logs", "a" * 64),
                consume=output.append,
                deadline=kwargs.pop("deadline", time.monotonic() + 5),
                **kwargs,
            )
        self.assertIs(popen.call_args.kwargs["shell"], False)
        self.assertEqual(popen.call_args.kwargs["stdin"], subprocess.DEVNULL)
        return result, output, process

    def test_chunk_boundaries_preserve_records_and_partial_tail_is_discarded(self):
        result, output, process = self.drain([b'{"a":', b"1}\nvalid\npartial"])
        self.assertEqual(output, [b'{"a":1}\n', b"valid\n"])
        self.assertEqual(result.discarded, 1)
        self.assertIsNone(result.reason)
        process.kill.assert_not_called()

    def test_input_byte_line_and_deadline_limits_kill_only_local_process(self):
        for chunks, options, reason in (
            ([b"0123456789"], {"max_bytes": 8}, "input_limit"),
            ([b"a\nb\n"], {"max_lines": 1}, "input_limit"),
            ([], {"deadline": time.monotonic() - 1}, "stream_timeout"),
        ):
            with self.subTest(options=options):
                result, _, process = self.drain(chunks, **options)
                self.assertEqual(result.reason, reason)
                process.kill.assert_called_once()

    def test_oversized_line_does_not_expand_buffer_or_poison_following_record(self):
        result, output, _ = self.drain([b"123456", b"789\nok\n"], max_line_bytes=4)
        self.assertEqual(result.discarded, 1)
        self.assertEqual(output, [b"ok\n"])

    def test_metadata_discards_stderr_and_reports_static_failure(self):
        with patch(
            "mcp_log_stream.stream_command",
            return_value=MagicMock(reason="stream_failed", discarded=0),
        ) as run:
            with self.assertRaisesRegex(ValueError, "^binding_probe_failed$"):
                bounded_metadata(("docker", "inspect"), deadline=time.monotonic() + 1)
            self.assertNotIn("include_stderr", run.call_args.kwargs)

    @unittest.skipUnless(
        sys.platform == "linux", "Linux operator pipe selector qualification"
    )
    def test_actual_linux_subprocess_timeout_and_bounded_stdout(self):
        rows = []
        result = stream_command(
            (
                sys.executable,
                "-c",
                "import time; print('safe', flush=True); time.sleep(20)",
            ),
            consume=rows.append,
            deadline=time.monotonic() + 0.3,
        )
        self.assertEqual(rows, [b"safe\n"])
        self.assertEqual(result.reason, "stream_timeout")


if __name__ == "__main__":
    unittest.main()
