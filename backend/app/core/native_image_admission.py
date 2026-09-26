"""Bound native pixel memory across threads and worker processes in one container.

Acquire BEFORE decoding and hold until every native image is closed. The kernel
owns both the four bounded waiting tickets and single execution lock, so a dead
worker cannot strand a lease or allow an expired lease to overlap live work.
Independent API containers have independent files and memory limits.
"""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import cache, wraps
from pathlib import Path
from typing import ParamSpec, TypeVar

from app.domain.exceptions.resource_capacity import ImageProcessingBusy

MAX_ADMITTED_IMAGE_OPERATIONS = 4
IMAGE_ADMISSION_WAIT_SECONDS = 5.0
_POLL_SECONDS = 0.01
_P = ParamSpec("_P")
_R = TypeVar("_R")
_open_descriptors: set[int] = set()


class _Ownership(threading.local):
    owner: tuple[int, int, str] | None = None


_ownership = _Ownership()


@cache
def _heap_reclaimer() -> Callable[[], None]:
    """The qualified GNU runtime must return freed native arenas to the OS.

    Closing Pillow buffers releases allocations, but a persistent worker's
    libc can retain those pages. Reclaim before another process gets the slot.
    """
    if sys.platform != "linux":
        return lambda: None
    try:
        library = ctypes.CDLL(None)
        getattr(library, "gnu_get_libc_version")
        trim = library.malloc_trim
    except (AttributeError, OSError):
        # An unqualified Linux allocator must not silently bypass reclamation.
        raise ImageProcessingBusy() from None
    trim.argtypes = [ctypes.c_size_t]
    trim.restype = ctypes.c_int

    def reclaim() -> None:
        # Zero means no pages were releasable, not an allocator error.
        trim(0)

    return reclaim


def _after_fork() -> None:
    # A parser child must not extend another thread's kernel lock lifetime.
    for descriptor in tuple(_open_descriptors):
        os.close(descriptor)
    _open_descriptors.clear()
    _ownership.owner = None


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork)


def _lock_directory() -> Path:
    return Path(tempfile.gettempdir()) / "passdetection-native-images-v1"


def _open_lock(directory: Path, name: str) -> int:
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise OSError("Invalid admission directory")
    if sys.platform != "win32" and (info.st_uid != os.geteuid() or info.st_mode & 0o022):
        raise OSError("Unsafe admission directory")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(directory / name, flags, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise OSError("Invalid admission lock")
        if sys.platform != "win32" and (info.st_uid != os.geteuid() or info.st_mode & 0o077):
            raise OSError("Unsafe admission lock")
        # Both flock and Windows byte-range locks permit an empty file. Never
        # initialize a byte here: another opener may already hold that range.
        _open_descriptors.add(descriptor)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _close_lock(descriptor: int) -> None:
    _open_descriptors.discard(descriptor)
    os.close(descriptor)


def _try_lock(descriptor: int) -> bool:
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as exc:
        if exc.errno in {errno.EAGAIN, errno.EACCES, errno.EDEADLK}:
            return False
        raise


@contextmanager
def native_image_slot(
    *, directory: Path | None = None, wait_seconds: float = IMAGE_ADMISSION_WAIT_SECONDS,
) -> Iterator[None]:
    """At most one decoder, four admitted calls, bounded wait with no decoded queue.

    Nested synchronous helpers in the SAME owning thread reuse its slot. Task
    cancellation cannot release it: the actual native worker owns this context.
    Never unlink the files: doing so could create two independent lock inodes.
    """
    if not 0 <= wait_seconds <= IMAGE_ADMISSION_WAIT_SECONDS:
        raise ValueError("Invalid image admission wait")
    directory = directory if directory is not None else _lock_directory()
    owner = (os.getpid(), threading.get_ident(), str(directory))
    if _ownership.owner == owner:
        yield
        return
    reclaim_heap = _heap_reclaimer()
    ticket: int | None = None
    execution: int | None = None
    previous_owner = _ownership.owner
    try:
        try:
            for index in range(MAX_ADMITTED_IMAGE_OPERATIONS):
                candidate = _open_lock(directory, f"ticket-{index}.lock")
                try:
                    if _try_lock(candidate):
                        ticket = candidate
                        break
                finally:
                    if ticket != candidate:
                        _close_lock(candidate)
            if ticket is None:
                raise ImageProcessingBusy()
            execution = _open_lock(directory, "execution.lock")
            deadline = time.monotonic() + wait_seconds
            while not _try_lock(execution):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ImageProcessingBusy()
                time.sleep(min(_POLL_SECONDS, remaining))
        except OSError:
            # Permissions, unsafe paths and unavailable locking never bypass it.
            raise ImageProcessingBusy() from None
        _ownership.owner = owner
        try:
            yield
        finally:
            reclaim_heap()
    finally:
        _ownership.owner = previous_owner
        if execution is not None:
            _close_lock(execution)
        if ticket is not None:
            _close_lock(ticket)


def bounded_native_image(operation: Callable[_P, _R]) -> Callable[_P, _R]:
    """Decorate a complete synchronous pixel lifetime, including nested helpers."""
    @wraps(operation)
    def run(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with native_image_slot():
            return operation(*args, **kwargs)
    return run
