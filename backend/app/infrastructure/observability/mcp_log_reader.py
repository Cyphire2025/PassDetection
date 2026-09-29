"""Read bounded copies from a dedicated operator-configured log mount.

No request supplies a path. The default has no collector and reports unavailable;
stdout, a Docker socket and arbitrary host logs are never fallbacks. A collector
must normalize each selected stream to JSON lines in these five fixed files.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOG_SOURCES = frozenset({"api", "worker", "frontend", "integration", "proxy"})
MAX_SCAN_BYTES = 512 * 1024
MAX_SCAN_RECORDS = 2000
MAX_LINE_BYTES = 16 * 1024


@dataclass(frozen=True)
class LogSlice:
    records: tuple[dict[str, Any], ...] = ()
    available: bool = True
    reason: str | None = None
    truncated: bool = False
    unreadable_records: int = 0
    collector_observed_at: str | None = None
    collector_window: dict[str, str] | None = None
    collector_reason: str | None = None


class MountedMCPLogReader:
    def __init__(self, root: Path | None = None):
        self._root = root

    async def read(self, source: str) -> LogSlice:
        if source not in LOG_SOURCES:
            raise ValueError("Unsupported diagnostic log source")
        if self._root is None:
            return LogSlice(available=False, reason="collector_not_configured")
        return await asyncio.to_thread(self._read, source)

    def _read(self, source: str) -> LogSlice:
        assert self._root is not None
        try:
            root = self._root.resolve(strict=True)
            path = root / f"{source}.jsonl"
            # Reject aliases even inside the approved mount. fstat below rejects
            # special files; O_NOFOLLOW closes the final symlink race on Linux.
            if path.is_symlink() or path.resolve(strict=True).parent != root:
                return LogSlice(available=False, reason="unsafe_collector_file")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                path_info = path.stat(follow_symlinks=False)
                if (not stat.S_ISREG(info.st_mode) or not stat.S_ISREG(path_info.st_mode)
                        or (info.st_dev, info.st_ino) != (path_info.st_dev, path_info.st_ino)):
                    return LogSlice(available=False, reason="unsafe_collector_file")
                start = max(0, info.st_size - MAX_SCAN_BYTES)
                stream.seek(start)
                data = stream.read(MAX_SCAN_BYTES)
        except FileNotFoundError:
            return LogSlice(available=False, reason="collector_file_missing")
        except OSError:
            return LogSlice(available=False, reason="collector_unreadable")

        truncated = start > 0
        lines = data.split(b"\n")
        if start:
            lines = lines[1:]  # the first record may have been cut in half
        if lines[-1]:
            truncated = True  # an in-progress write is never returned as a record
        lines = lines[:-1]
        if len(lines) > MAX_SCAN_RECORDS:
            truncated = True
            lines = lines[-MAX_SCAN_RECORDS:]
        records, unreadable = [], 0
        for line in lines:
            if not line:
                continue
            try:
                if len(line) > MAX_LINE_BYTES:
                    raise ValueError()
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError()
                records.append(record)
            except (ValueError, UnicodeDecodeError, RecursionError):
                unreadable += 1
        return LogSlice(tuple(records), truncated=truncated, unreadable_records=unreadable)
