from __future__ import annotations

import asyncio
import threading
import time

import bcrypt
import pytest
from pydantic import ValidationError

from app.core.security.password import hash_password, run_password_work, verify_password
from app.domain.exceptions.exceptions import DependencyUnavailableError
from app.presentation.api.v1.schemas.auth_schemas import (
    CompleteIdentityActionRequest,
    PasswordChangeRequest,
)
from app.presentation.api.v1.schemas.mobile_schemas import (
    MobileActivationRequest,
    MobilePasswordChangeRequest,
)


@pytest.mark.parametrize("prefix", ["Aa1", "Aa1é"])
def test_new_password_byte_limit_is_exact_and_never_truncates(prefix):
    exact = prefix + "x" * (72 - len(prefix.encode("utf-8")))
    hashed = hash_password(exact)
    assert verify_password(exact, hashed)
    with pytest.raises(ValueError, match="72 UTF-8 bytes"):
        hash_password(exact + "x")


@pytest.mark.parametrize("legacy", ["Aa1" + "x" * 90, "Aa1" + "é" * 40])
def test_legacy_long_credentials_keep_original_bcrypt_verification_equivalence(legacy):
    # Real retained bcrypt hashes encode only these first72 bytes. The UTF-8
    # case deliberately ends in the first byte of a multibyte code point.
    hashed = bcrypt.hashpw(legacy.encode("utf-8")[:72], bcrypt.gensalt(rounds=4)).decode("ascii")
    assert verify_password(legacy, hashed)
    assert verify_password(legacy + "different-legacy-suffix", hashed)
    assert not verify_password("WrongPrefix1" + legacy, hashed)
    with pytest.raises(ValueError, match="72 UTF-8 bytes"):
        hash_password(legacy)


@pytest.mark.parametrize("model,kwargs", [
    (CompleteIdentityActionRequest, {"token": "x" * 32}),
    (PasswordChangeRequest, {"current_password": "CurrentPassword1"}),
    (MobileActivationRequest, {"activation_token": "x" * 32, "device": {"installation_id": "x" * 16, "platform": "android", "app_version": "1.0.0"}}),
    (MobilePasswordChangeRequest, {"current_password": "CurrentPassword1", "device": {"installation_id": "x" * 16, "platform": "android", "app_version": "1.0.0"}}),
])
def test_new_password_schemas_reject_utf8_overflow_before_hashing(model, kwargs):
    assert model(new_password="Aa1" + "x" * 69, **kwargs).new_password
    with pytest.raises(ValidationError, match="72 UTF-8 bytes"):
        model(new_password="Aa1" + "é" * 35, **kwargs)


@pytest.mark.asyncio
async def test_password_threads_do_not_block_loop_and_reject_unbounded_work():
    started = 0
    lock, release = threading.Lock(), threading.Event()
    def work():
        nonlocal started
        with lock:
            started += 1
        release.wait(2)
        return True
    tasks = [asyncio.create_task(run_password_work(work)) for _ in range(4)]
    try:
        for _ in range(100):
            if started == 4:
                break
            await asyncio.sleep(0.005)
        assert started == 4
        tick = time.monotonic()
        await asyncio.sleep(0.02)
        assert time.monotonic() - tick < 0.2
        with pytest.raises(DependencyUnavailableError):
            await run_password_work(work)
    finally:
        release.set()
        await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_cancelled_request_does_not_release_running_password_worker_budget():
    started = threading.Event()
    release = threading.Event()
    def work():
        started.set()
        release.wait(2)
    task = asyncio.create_task(run_password_work(work))
    while not started.is_set():
        await asyncio.sleep(0.005)
    task.cancel()
    await asyncio.sleep(0.02)
    from app.core.security.password import _password_admission
    try:
        assert _password_admission.get().borrowed_tokens == 1
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert _password_admission.get().borrowed_tokens == 0
