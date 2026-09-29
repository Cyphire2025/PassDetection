"""Sealed append-only diagnostic run selection with strict integrity and freshness."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.logging.mcp_log_projection import diagnostic_timestamp
from app.infrastructure.observability.mcp_log_reader import (
    LOG_SOURCES,
    MAX_SCAN_BYTES,
    MAX_SCAN_RECORDS,
    LogSlice,
    MountedMCPLogReader,
)

MAX_RUNS = 128
MAX_MANIFEST_BYTES = 32 * 1024
MAX_FRESHNESS_SECONDS = 300
RUN_NAME = re.compile(r"run-\d{8}T\d{6}Z-[a-f0-9]{32}")
FAILURE_CODES = frozenset(
    {
        "source_unavailable",
        "source_ambiguous",
        "binding_changed",
        "stream_failed",
        "stream_timeout",
        "input_limit",
        "output_limit",
        "invalid_records",
        "collection_deadline",
    }
)


class CollectorRunError(ValueError):
    pass


def safe_file(root: Path, name: str, maximum: int) -> bytes:
    path = root / name
    if (
        root.is_symlink()
        or path.is_symlink()
        or path.resolve(strict=True).parent != root.resolve(strict=True)
    ):
        raise CollectorRunError("unsafe_collector_file")
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    )
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        current = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or info.st_nlink != 1
            or (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino)
            or info.st_size > maximum
        ):
            raise CollectorRunError("unsafe_collector_file")
        data = stream.read(maximum + 1)
        if len(data) > maximum or len(data) != info.st_size:
            raise CollectorRunError("collector_integrity_failed")
        return data


def latest_run(root: Path) -> Path:
    if root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise CollectorRunError("unsafe_collector_root")
    selected: Path | None = None
    newest: Path | None = None
    seen_times: set[str] = set()
    with os.scandir(root) as entries:
        for index, entry in enumerate(entries):
            if index >= MAX_RUNS:
                raise CollectorRunError("collector_run_limit")
            if (
                not RUN_NAME.fullmatch(entry.name)
                or entry.is_symlink()
                or not entry.is_dir(follow_symlinks=False)
            ):
                raise CollectorRunError("unsafe_collector_root")
            path = Path(entry.path)
            if entry.name[:20] in seen_times:
                raise CollectorRunError("collector_run_order_ambiguous")
            seen_times.add(entry.name[:20])
            if newest is None or path.name > newest.name:
                newest = path
            # An interrupted unsealed run remains on disk but cannot be served.
            if (path / "manifest.json").is_file() and (
                selected is None or path.name > selected.name
            ):
                selected = path
    if selected is None:
        raise CollectorRunError("collector_no_sealed_run")
    if newest != selected:
        raise CollectorRunError("collector_latest_run_incomplete")
    return selected


def verified_manifest(path: Path, now: datetime) -> dict[str, Any]:
    manifest = json.loads(safe_file(path, "manifest.json", MAX_MANIFEST_BYTES))
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("schema_version")) is not int
        or manifest["schema_version"] != 1
        or manifest.get("run_id") != path.name
    ):
        raise CollectorRunError("collector_manifest_invalid")
    start, finish, since, until = [
        diagnostic_timestamp(manifest.get(key))
        for key in ("started_at", "finished_at", "collection_since", "collection_until")
    ]
    if (
        start is None
        or finish is None
        or since is None
        or until is None
        or not since <= until <= finish
        or (start is not None and path.name[4:20] != start.strftime("%Y%m%dT%H%M%SZ"))
        or start > finish
        or (finish - start).total_seconds() > 120
        or (until - since).total_seconds() > 900
    ):
        raise CollectorRunError("collector_manifest_invalid")
    age = (now - finish).total_seconds()
    if age < -30:
        raise CollectorRunError("collector_clock_invalid")
    if age > MAX_FRESHNESS_SECONDS:
        raise CollectorRunError("collector_stale")
    sources = manifest.get("sources")
    if not isinstance(sources, dict) or set(sources) != LOG_SOURCES:
        raise CollectorRunError("collector_manifest_invalid")
    for source, entry in sources.items():
        if (
            not isinstance(entry, dict)
            or entry.get("file") != f"{source}.jsonl"
            or entry.get("status") not in {"available", "partial", "unavailable"}
        ):
            raise CollectorRunError("collector_manifest_invalid")
        if entry.get("reason") is not None and entry["reason"] not in FAILURE_CODES:
            raise CollectorRunError("collector_manifest_invalid")
        if (entry["status"] == "available") != (entry.get("reason") is None):
            raise CollectorRunError("collector_manifest_invalid")
        if (
            type(entry.get("size_bytes")) is not int
            or not 0 <= entry["size_bytes"] <= MAX_SCAN_BYTES
            or type(entry.get("records")) is not int
            or not 0 <= entry["records"] <= MAX_SCAN_RECORDS
        ):
            raise CollectorRunError("collector_manifest_invalid")
        if (
            type(entry.get("discarded")) is not int
            or not 0 <= entry["discarded"] <= 1_000_000
            or type(entry.get("input_truncated")) is not bool
        ):
            raise CollectorRunError("collector_manifest_invalid")
        if not isinstance(entry.get("sha256"), str) or not re.fullmatch(
            "[a-f0-9]{64}", entry["sha256"]
        ):
            raise CollectorRunError("collector_manifest_invalid")
    return manifest


class SealedMCPLogReader(MountedMCPLogReader):
    """Production mount reader; legacy unsealed fixture files are never selected."""

    async def read(self, source: str) -> LogSlice:
        if source not in LOG_SOURCES:
            raise ValueError("Unsupported diagnostic log source")
        if self._root is None:
            return LogSlice(available=False, reason="collector_not_configured")
        return await asyncio.to_thread(self._sealed_read, source)

    def _sealed_read(self, source: str) -> LogSlice:
        assert self._root is not None
        try:
            run = latest_run(self._root)
            manifest = verified_manifest(run, datetime.now(UTC))
            entry = manifest["sources"][source]
            data = safe_file(run, entry["file"], MAX_SCAN_BYTES)
            if (
                len(data) != entry["size_bytes"]
                or hashlib.sha256(data).hexdigest() != entry["sha256"]
            ):
                raise CollectorRunError("collector_integrity_failed")
            if entry["status"] == "unavailable":
                return LogSlice(
                    available=False,
                    reason=entry["reason"] or "source_unavailable",
                    collector_observed_at=manifest["finished_at"],
                )
            records = []
            for line in data.splitlines():
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise CollectorRunError("collector_integrity_failed")
                records.append(record)
            if len(records) != entry["records"] or (data and not data.endswith(b"\n")):
                raise CollectorRunError("collector_integrity_failed")
            return LogSlice(
                tuple(records),
                truncated=entry["status"] == "partial" or entry["input_truncated"],
                unreadable_records=entry["discarded"],
                collector_observed_at=manifest["finished_at"],
                collector_window={
                    "since": manifest["collection_since"],
                    "until": manifest["collection_until"],
                },
                collector_reason=entry["reason"],
            )
        except CollectorRunError as exc:
            return LogSlice(available=False, reason=str(exc))
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            return LogSlice(available=False, reason="collector_unreadable")
