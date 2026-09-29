"""Exclusive diagnostic run writes; bounded retained directory, no deletion or replacement."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from app.core.logging.mcp_log_projection import (
    diagnostic_timestamp,
    project_diagnostic_record,
)
from app.infrastructure.observability.mcp_log_reader import (
    LOG_SOURCES,
    MAX_SCAN_BYTES,
    MAX_SCAN_RECORDS,
)
from app.infrastructure.observability.mcp_log_runs import (
    FAILURE_CODES,
    MAX_MANIFEST_BYTES,
    MAX_RUNS,
    RUN_NAME,
)

MAX_ROOT_BYTES = 64 * 1024 * 1024
MAX_RUN_BYTES = len(LOG_SOURCES) * MAX_SCAN_BYTES + MAX_MANIFEST_BYTES
FIXED_FILES = {f"{source}.jsonl" for source in LOG_SOURCES} | {"manifest.json"}


def admit_output_root(root: Path) -> None:
    """Reject unknown entries, aliases and excess capacity without altering them."""
    if (
        not root.is_absolute()
        or root.is_symlink()
        or not root.is_dir()
        or root.resolve() != root
    ):
        raise ValueError("unsafe_output_root")
    total = 0
    with os.scandir(root) as runs:
        for index, run in enumerate(runs):
            if index >= MAX_RUNS - 1:
                raise ValueError("output_run_limit")
            if (
                not RUN_NAME.fullmatch(run.name)
                or run.is_symlink()
                or not run.is_dir(follow_symlinks=False)
            ):
                raise ValueError("unsafe_output_root")
            with os.scandir(run.path) as entries:
                for number, entry in enumerate(entries):
                    if (
                        number >= len(FIXED_FILES)
                        or entry.name not in FIXED_FILES
                        or entry.is_symlink()
                    ):
                        raise ValueError("unsafe_output_root")
                    info = os.stat(entry.path, follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        raise ValueError("unsafe_output_root")
                    total += info.st_size
                    if total + MAX_RUN_BYTES > MAX_ROOT_BYTES:
                        raise ValueError("output_disk_budget")


class SourceBuffer:
    def __init__(self) -> None:
        self.lines: list[bytes] = []
        self.size = 0
        self.discarded = 0
        self.successful_services = 0
        self.failure: str | None = None

    def add(self, record: dict[str, Any]) -> None:
        stamp = diagnostic_timestamp(record.get("timestamp"))
        if stamp is None:
            self.discarded += 1
            self.failure = self.failure or "invalid_records"
            return
        line = (
            json.dumps(
                project_diagnostic_record(record, stamp),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        if (
            self.size + len(line) > MAX_SCAN_BYTES
            or len(self.lines) >= MAX_SCAN_RECORDS
        ):
            self.failure = "output_limit"
            return
        self.lines.append(line)
        self.size += len(line)

    def entry(self, source: str) -> tuple[bytes, dict[str, Any]]:
        if source not in LOG_SOURCES or (
            self.failure is not None and self.failure not in FAILURE_CODES
        ):
            raise ValueError("invalid_source_state")
        data = b"".join(self.lines)
        status = (
            "available"
            if self.failure is None
            else "partial"
            if self.successful_services or self.lines
            else "unavailable"
        )
        return data, {
            "file": f"{source}.jsonl",
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "records": len(self.lines),
            "discarded": min(self.discarded, 1_000_000),
            "input_truncated": self.failure
            in {"input_limit", "stream_timeout", "collection_deadline", "output_limit"},
            "status": status,
            "reason": self.failure,
        }


def exclusive_bytes(directory: Path, name: str, data: bytes, gid: int) -> None:
    if name not in FIXED_FILES:
        raise ValueError("invalid_output_file")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(directory / name, flags, 0o640)
    with os.fdopen(descriptor, "wb") as stream:
        if hasattr(os, "fchown"):
            os.fchown(stream.fileno(), -1, gid)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def create_run(root: Path, run_id: str) -> Path:
    if not RUN_NAME.fullmatch(run_id):
        raise ValueError("invalid_run_id")
    admit_output_root(root)
    with os.scandir(root) as entries:
        if any(entry.name[:20] == run_id[:20] for entry in entries):
            raise ValueError("output_run_time_collision")
    run = root / run_id
    run.mkdir(mode=0o750, exist_ok=False)
    if hasattr(os, "chown"):
        os.chown(run, -1, root.stat().st_gid)
    return run


def seal_run(
    root: Path, run: Path, manifest: dict[str, Any], sources: dict[str, SourceBuffer]
) -> None:
    if run.parent != root or run.is_symlink() or set(sources) != LOG_SOURCES:
        raise ValueError("invalid_output_run")
    entries = {}
    for source in sorted(LOG_SOURCES):
        data, entries[source] = sources[source].entry(source)
        exclusive_bytes(run, f"{source}.jsonl", data, root.stat().st_gid)
    manifest["sources"] = entries
    encoded = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ValueError("manifest_budget")
    exclusive_bytes(run, "manifest.json", encoded, root.stat().st_gid)
