"""Exercise the native qualification test's cleanup without OS vault/process access."""

import asyncio

import pytest
import test_windows_vault_native as native


class SyntheticProcess:
    def __init__(self, events, *, mode, raced_exit=False):
        self.events = events
        self.mode = mode
        self.raced_exit = raced_exit
        self.returncode = 0 if mode == "success" else None
        self.entered = asyncio.Event()
        self.waiting = asyncio.Event()
        self.release_wait = asyncio.Event()
        self.release_wait.set()

    async def communicate(self):
        self.entered.set()
        if self.mode == "success":
            return b"synthetic credential recovered", b""
        await asyncio.Event().wait()

    def kill(self):
        self.events.append("kill")
        if self.raced_exit:
            self.returncode = 0
            raise ProcessLookupError("Synthetic child already exited")

    async def wait(self):
        self.waiting.set()
        await self.release_wait.wait()
        self.returncode = 0
        self.events.append("reaped")
        return 0


def install_synthetic_boundary(monkeypatch, *, mode, raced_exit=False):
    events = []
    child = SyntheticProcess(events, mode=mode, raced_exit=raced_exit)

    class Vault:
        def __init__(self, key):
            assert key.startswith("GlobalConnects-MCP-qualification-")
            self.value = None

        def read(self):
            return self.value

        def write(self, value):
            events.append("write")
            self.value = value

        def delete(self):
            events.append("delete")
            self.value = None

    async def create(*_args, **_kwargs):
        events.append("spawn")
        return child

    original_wait = asyncio.wait_for

    async def bounded_wait(awaitable, _timeout):
        return await original_wait(awaitable, 0.01)

    monkeypatch.setattr(native, "WindowsVault", Vault)
    monkeypatch.setattr(native.asyncio, "create_subprocess_exec", create)
    monkeypatch.setattr(native.asyncio, "wait_for", bounded_wait)
    return child, events


@pytest.mark.parametrize(
    "mode,raced_exit", [("timeout", False), ("cancel", False), ("timeout", True)]
)
async def test_real_qualification_timeout_or_cancel_reaps_before_vault_delete(
    monkeypatch, mode, raced_exit
):
    child, events = install_synthetic_boundary(monkeypatch, mode=mode, raced_exit=raced_exit)
    task = asyncio.create_task(native.test_native_vault_round_trip_survives_a_process_boundary())
    await child.entered.wait()
    if mode == "cancel":
        task.cancel()
    with pytest.raises(asyncio.CancelledError if mode == "cancel" else TimeoutError):
        await task
    assert events[-2:] == ["reaped", "delete"]
    assert events.count("kill") == 1


async def test_real_qualification_success_preserves_assertions_and_does_not_kill_exited_child(
    monkeypatch,
):
    _child, events = install_synthetic_boundary(monkeypatch, mode="success")
    await native.test_native_vault_round_trip_survives_a_process_boundary()
    assert "kill" not in events
    assert events[-2:] == ["reaped", "delete"]


async def test_repeated_cancellation_waits_for_reaping_before_deleting_synthetic_target(
    monkeypatch,
):
    child, events = install_synthetic_boundary(monkeypatch, mode="cancel")
    child.release_wait.clear()
    task = asyncio.create_task(native.test_native_vault_round_trip_survives_a_process_boundary())
    try:
        async with asyncio.timeout(1):
            await child.entered.wait()
            task.cancel()
            await child.waiting.wait()
            assert "delete" not in events
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and "delete" not in events
            child.release_wait.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert events[-2:] == ["reaped", "delete"]
        assert events.count("kill") == 1
    finally:
        child.release_wait.set()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
