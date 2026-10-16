"""Admission and early pressure detection within the backend's existing cap."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

MIB = 1024**2
HOST_RESERVE_BYTES = 2048 * MIB
START_RESERVE_BYTES = 256 * MIB
STOP_RESERVE_BYTES = 160 * MIB
ESTIMATED_CHECKER_BYTES = 192 * MIB


@dataclass(frozen=True, slots=True)
class PdfMemorySnapshot:
    remaining_bytes: int
    host_available_bytes: int

    @property
    def parser_headroom_bytes(self) -> int:
        return min(self.remaining_bytes, self.host_available_bytes - HOST_RESERVE_BYTES)


def memory_snapshot() -> PdfMemorySnapshot | None:
    if sys.platform != "linux":
        return None
    try:
        root = Path("/sys/fs/cgroup")
        limit = int((root / "memory.max").read_text().strip())
        used = int((root / "memory.current").read_text().strip())
        info = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
        available = int(info["MemAvailable"].split()[0]) * 1024
        if limit <= 0 or used < 0 or available < 0:
            return None
        return PdfMemorySnapshot(
            remaining_bytes=max(0, limit - used), host_available_bytes=available
        )
    except (OSError, ValueError, KeyError):
        return None


def affordable_processes(requested: int, source_bytes: int, *, required: bool) -> int:
    snapshot = memory_snapshot()
    if snapshot is None:
        # Windows has no Linux cgroup. A production Linux API must have the
        # bounded cgroup installed by the release's inspected resource profile.
        return 0 if required and sys.platform == "linux" else requested
    allowance = snapshot.parser_headroom_bytes - START_RESERVE_BYTES - 2 * source_bytes
    return min(requested, max(0, allowance // ESTIMATED_CHECKER_BYTES))


def memory_under_pressure() -> bool:
    snapshot = memory_snapshot()
    return snapshot is not None and snapshot.parser_headroom_bytes < STOP_RESERVE_BYTES
