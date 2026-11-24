"""Bound command time, captured memory and private diagnostic bytes continuously."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from bounded_command_output import CommandOutputError, capture_command
from qa.qualify_postgresql_client import QualificationError


def capture(arguments: list[str], *, timeout: int, maximum_bytes: int = 2 * 1024 * 1024,
            diagnostic_path: Path | None = None) -> str:
    with (os.fdopen(os.open(diagnostic_path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600), "w+b")
          if diagnostic_path is not None else tempfile.TemporaryFile()) as output:
        try:
            capture_command(arguments, timeout=timeout, maximum_bytes=maximum_bytes, output=output)
        except CommandOutputError as error:
            reasons = {
                "output_limit_or_capture_failed": "migration_output_limit_or_capture_failed",
                "command_failed": "populated_migration_helper_failed",
                "capture_failed_or_timed_out": "populated_migration_command_failed_or_timed_out",
            }
            raise QualificationError(reasons[error.reason]) from None
        output.flush()
        if diagnostic_path is not None:
            os.fsync(output.fileno())
        output.seek(0)
        return output.read(maximum_bytes).decode("utf-8", errors="replace")
