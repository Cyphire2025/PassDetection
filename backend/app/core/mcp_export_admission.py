"""One nonwaiting MCP export body across workers sharing a container tempdir.

The owning async task holds the kernel lease before source materialization and
through drained render/storage work. The kernel releases it if the worker dies.
This is independent of the native image gate, which is always acquired later.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from app.core.native_image_admission import _close_lock, _open_lock, _try_lock


class ExportAdmissionBusy(RuntimeError):
    """Shared export admission is unavailable; callers must retry explicitly."""


_owner: ContextVar[tuple[int, object, str] | None] = ContextVar("mcp_export_owner", default=None)


@contextmanager
def export_slot(*, directory: Path | None = None) -> Iterator[None]:
    """Reuse only the same task's lease, never a child task's inherited context."""
    task = asyncio.current_task()
    if task is None:
        raise RuntimeError("MCP export admission requires an async task")
    directory = directory or Path(tempfile.gettempdir()) / "passdetection-mcp-exports-v1"
    owner = (os.getpid(), task, str(directory))
    if _owner.get() == owner:
        yield
        return
    descriptor: int | None = None
    try:
        # Reuse the validated no-symlink, owner/mode, cross-platform kernel
        # helpers and fork-descriptor cleanup already used for native images.
        descriptor = _open_lock(directory, "execute.lock")
        if not _try_lock(descriptor):
            raise ExportAdmissionBusy()
    except OSError as exc:
        if descriptor is not None:
            _close_lock(descriptor)
            descriptor = None
        raise ExportAdmissionBusy() from exc
    except ExportAdmissionBusy:
        if descriptor is not None:
            _close_lock(descriptor)
        raise
    token = _owner.set(owner)
    try:
        yield
    finally:
        _owner.reset(token)
        _close_lock(descriptor)
