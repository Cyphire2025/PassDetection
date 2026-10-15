"""Bound command time, captured memory and private diagnostic bytes continuously."""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading
from pathlib import Path

from qa.qualify_postgresql_client import QualificationError


def capture(arguments: list[str], *, timeout: int, maximum_bytes: int = 2 * 1024 * 1024,
            diagnostic_path: Path | None = None) -> str:
    exceeded = threading.Event()
    failures: list[Exception] = []
    with (os.fdopen(os.open(diagnostic_path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600), "w+b")
          if diagnostic_path is not None else tempfile.TemporaryFile()) as output:
        try:
            with subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
                assert process.stdout is not None
                pipe = process.stdout

                def consume() -> None:
                    size = 0
                    try:
                        while chunk := pipe.read(8192):
                            remaining = maximum_bytes - size
                            output.write(chunk[:remaining])
                            size += len(chunk)
                            if size > maximum_bytes:
                                exceeded.set()
                                process.kill()
                                break
                    except OSError as error:
                        failures.append(error)
                        process.kill()

                reader = threading.Thread(target=consume, daemon=True)
                reader.start()
                try:
                    code = process.wait(timeout=timeout)
                except BaseException:
                    process.kill()
                    process.wait(timeout=10)
                    raise
                finally:
                    reader.join(timeout=10)
                if reader.is_alive() or failures or exceeded.is_set():
                    raise QualificationError("migration_output_limit_or_capture_failed")
                if code:
                    raise QualificationError("populated_migration_helper_failed")
        except (OSError, subprocess.TimeoutExpired):
            raise QualificationError("populated_migration_command_failed_or_timed_out") from None
        output.flush()
        if diagnostic_path is not None:
            os.fsync(output.fileno())
        output.seek(0)
        return output.read(maximum_bytes).decode("utf-8", errors="replace")
