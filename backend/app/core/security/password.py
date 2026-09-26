"""
Password Hashing Utilities
==========================
Wraps bcrypt directly for consistent password hashing across the platform.

Rules:
  - Never store or log plaintext passwords.
  - Always verify using this module — never compare strings directly.
"""

import asyncio
import re
from collections.abc import Callable
from typing import TypeVar

import bcrypt
from anyio import CancelScope, CapacityLimiter, WouldBlock, to_thread
from anyio.lowlevel import RunVar

from app.domain.exceptions.exceptions import DependencyUnavailableError

PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_BYTES = 72
DUMMY_PASSWORD_HASH = "$2b$12$UNslkxiKhfVqyfCKD8VxsuRfyiTkzySdJYnzFZNrMWNTVfgCC.GlG"
_PASSWORD_WORKERS = 4
_password_admission: RunVar[CapacityLimiter] = RunVar("password_admission")
_password_threads: RunVar[CapacityLimiter] = RunVar("password_threads")
_Result = TypeVar("_Result")


async def run_password_work(operation: Callable[..., _Result], *args: str) -> _Result:
    """Run bcrypt outside the event loop with a bounded, cancellation-safe budget.

    No unbounded queue of expensive password work is admitted. A saturated
    process returns the ordinary dependency-unavailable response; cancellation
    waits for the worker before releasing its slot.
    """
    try:
        admission, threads = _password_admission.get(), _password_threads.get()
    except LookupError:
        admission, threads = CapacityLimiter(_PASSWORD_WORKERS), CapacityLimiter(_PASSWORD_WORKERS)
        _password_admission.set(admission)
        _password_threads.set(threads)
    try:
        admission.acquire_nowait()
    except WouldBlock as exc:
        raise DependencyUnavailableError("Authentication is busy. Please try again shortly.") from exc
    try:
        worker = asyncio.create_task(
            to_thread.run_sync(operation, *args, limiter=threads, abandon_on_cancel=False)
        )
        cancelled = False
        with CancelScope(shield=True):
            while True:
                try:
                    result = await asyncio.shield(worker)
                    break
                except asyncio.CancelledError:
                    # asyncio.Task.cancel() bypasses AnyIO's cancel scopes.
                    # Keep the admission slot until that real worker exits.
                    cancelled = True
                    if worker.done():
                        break
        if cancelled:
            # Retrieve a completed exception without leaking credentials into
            # an unhandled-task warning when the original request is gone.
            if not worker.cancelled():
                worker.exception()
            raise asyncio.CancelledError
        return result
    finally:
        admission.release()


def validate_password_bytes(password: str) -> str:
    """Reject rather than truncate passwords outside bcrypt's byte contract."""
    if len(password.encode("utf-8")) > PASSWORD_MAX_BYTES:
        raise ValueError(f"Password must be at most {PASSWORD_MAX_BYTES} UTF-8 bytes")
    return password


def validate_password_strength(password: str) -> None:
    """Enforce the shared password policy for account creation and reset."""
    validate_password_bytes(password)
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must include an uppercase letter")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must include a lowercase letter")
    if not re.search(r"\d", password):
        raise ValueError("Password must include a number")


def hash_password(plain_password: str) -> str:
    """
    Hash a plaintext password using bcrypt.

    Args:
        plain_password: The user-supplied password in plaintext.

    Returns:
        A bcrypt hash string safe to store in the database.
    """
    validate_password_strength(plain_password)
    pwd_bytes = plain_password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plaintext password against a stored bcrypt hash.

    Args:
        plain_password:   The password supplied during login.
        hashed_password:  The hash retrieved from the database.

    Returns:
        True if the password matches the hash, False otherwise.
    """
    # Older bcrypt releases silently limited verification to 72 bytes. Keep
    # retained hashes usable after the bcrypt 5 upgrade: suffix bytes were
    # never part of those credentials, including a split UTF-8 code point.
    # New/change/reset inputs are rejected above this limit before hashing.
    pwd_bytes = plain_password.encode("utf-8")[:PASSWORD_MAX_BYTES]
    hashed_bytes = hashed_password.encode("utf-8")
    try:
        return bcrypt.checkpw(pwd_bytes, hashed_bytes)
    except Exception:
        return False
