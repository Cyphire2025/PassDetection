"""Linux operator-only bounded subprocess reads; never shell or container mutation."""

from __future__ import annotations

import os
import selectors
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class CommandResult:
    reason: str | None
    input_bytes: int
    lines: int
    discarded: int


def stream_command(
    arguments: Sequence[str],
    *,
    consume: Callable[[bytes], None],
    deadline: float,
    max_bytes: int = 2 * 1024 * 1024,
    max_lines: int = 2000,
    max_line_bytes: int = 16 * 1024,
    include_stderr: bool = False,
) -> CommandResult:
    """Hard-limit buffers; optional log stderr passes through the same projection."""
    process = subprocess.Popen(
        list(arguments),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if include_stderr else subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        shell=False,
        close_fds=True,
    )
    assert process.stdout is not None
    buffer = bytearray()
    oversized = False
    total = lines = discarded = 0
    reason = None
    try:
        os.set_blocking(process.stdout.fileno(), False)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    reason = "stream_timeout"
                    break
                if not selector.select(min(remaining, 0.2)):
                    continue
                chunk = os.read(
                    process.stdout.fileno(), min(65536, max_bytes - total + 1)
                )
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    reason = "input_limit"
                    break
                for part in chunk.splitlines(keepends=True):
                    if not oversized:
                        if len(buffer) + len(part) > max_line_bytes:
                            buffer.clear()
                            oversized = True
                        else:
                            buffer.extend(part)
                    if part.endswith(b"\n"):
                        lines += 1
                        if oversized:
                            discarded += 1
                        else:
                            consume(bytes(buffer))
                        buffer.clear()
                        oversized = False
                        if lines >= max_lines:
                            reason = "input_limit"
                            break
                if reason:
                    break
            if buffer or oversized:
                discarded += 1
    finally:
        # Only terminate this local docker CLI subprocess, never a target service.
        if process.poll() is None:
            if reason is None:
                try:
                    process.wait(
                        timeout=max(0.0, min(2.0, deadline - time.monotonic()))
                    )
                except subprocess.TimeoutExpired:
                    reason = "stream_timeout"
                    process.kill()
            else:
                process.kill()
        process.wait(timeout=2)
        process.stdout.close()
    if reason is None and process.returncode:
        reason = "stream_failed"
    return CommandResult(reason, min(total, max_bytes), lines, discarded)


def bounded_metadata(
    arguments: Sequence[str], *, deadline: float, maximum: int = 512 * 1024
) -> bytes:
    rows: list[bytes] = []
    result = stream_command(
        arguments,
        consume=rows.append,
        deadline=deadline,
        max_bytes=maximum,
        max_lines=1024,
        max_line_bytes=maximum,
    )
    if result.reason is not None or result.discarded:
        raise ValueError("binding_probe_failed")
    return b"".join(rows)
