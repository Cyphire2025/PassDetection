"""The refresh consumer fences uncertain rotation without replaying a credential.

HTTP, vault and process-lock boundaries are synthetic. No native credential is
read or changed here; Windows mutex cleanup uses isolated mocked handles.
"""

import asyncio
import sys
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import anyio
import httpx2
import pytest

from gc_mcp_connector.auth import Authorization, ResourceBearerAuth
from gc_mcp_connector.config import Config, ConnectorError
from gc_mcp_connector.oauth import Tokens
from gc_mcp_connector.vault import Credential, WindowsCredentialLock

PRIVATE = "PRIVATE-REFRESH-CANCELLATION-SENTINEL"


class ConsumerVault:
    def __init__(
        self, *, delete_failure=False, delete_cancellation=False,
        write_cancellation=False, on_saved=None,
    ):
        self.credential = Credential(PRIVATE + "-old", time.time() + 6000)
        self.original = self.credential
        self.reads = 0
        self.deletes = 0
        self.writes = []
        self.delete_failure = delete_failure
        self.delete_error = asyncio.CancelledError(PRIVATE) if delete_cancellation else None
        self.write_cancellation = write_cancellation
        self.write_error = asyncio.CancelledError(PRIVATE)
        self.on_saved = on_saved
        self.held = False
        self.releases = 0

    @asynccontextmanager
    async def process_lock(self):
        assert not self.held
        self.held = True
        try:
            yield
        finally:
            self.held = False
            self.releases += 1

    def read(self):
        assert self.held
        self.reads += 1
        return self.credential

    def write(self, value):
        assert self.held
        if self.write_cancellation:
            raise self.write_error
        self.credential = value
        self.writes.append(value)
        if self.on_saved:
            self.on_saved()

    def delete(self):
        assert self.held  # Synchronous cleanup must precede process-lock release.
        self.deletes += 1
        if self.delete_error:
            raise self.delete_error
        if self.delete_failure:
            raise RuntimeError(PRIVATE)
        self.credential = None


def assert_private_output_absent(capsys, caplog):
    captured = capsys.readouterr()
    assert PRIVATE not in captured.out + captured.err + caplog.text


async def cancelled_consumer(auth, entered, mode):
    propagated = []
    scopes = []

    async def consume():
        if mode == "anyio":
            with anyio.CancelScope() as scope:
                scopes.append(scope)
                try:
                    await auth.access_token()
                except anyio.get_cancelled_exc_class():
                    propagated.append(True)
                    raise
        else:
            await auth.access_token()

    task = asyncio.create_task(consume())
    await entered.wait()
    if mode == "anyio":
        scopes[0].cancel()
        await task
        assert propagated == [True]
    else:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    return scopes


@pytest.mark.parametrize("mode", ["asyncio", "anyio"])
@pytest.mark.parametrize("delete_failure", [False, True])
async def test_uncertain_cancelled_refresh_clears_or_fences_credential_and_never_replays(
    mode, delete_failure, capsys, caplog,
):
    entered = asyncio.Event()
    calls = []

    async def consumed_refresh(value):
        calls.append(value)
        entered.set()  # The synthetic remote has consumed it; response is pending.
        await asyncio.Event().wait()

    vault = ConsumerVault(delete_failure=delete_failure)
    auth = Authorization(SimpleNamespace(refresh=consumed_refresh), vault, vault.process_lock)
    auth.authorized_until = vault.original.authorized_until
    await cancelled_consumer(auth, entered, mode)
    assert calls == [vault.original.refresh_token]
    assert vault.deletes == 1
    assert vault.credential == (vault.original if delete_failure else None)
    assert auth.tokens is None and auth.authorized_until is None
    assert not vault.held and vault.releases == 1 and not auth.lock.locked()
    # A later call must fail before another refresh, even if vault deletion failed.
    with pytest.raises(ConnectorError, match="Sign in"):
        await auth.access_token()
    assert len(calls) == 1 and vault.deletes == 1
    assert_private_output_absent(capsys, caplog)


@pytest.mark.parametrize("mode", ["asyncio", "anyio"])
async def test_cancellation_queued_before_refresh_preserves_existing_credential(mode, capsys, caplog):
    calls = []
    entered = asyncio.Event()
    vault = ConsumerVault()
    auth = Authorization(SimpleNamespace(refresh=lambda value: calls.append(value)), vault, vault.process_lock)
    scopes = []

    async def queued():
        with anyio.CancelScope() as scope:
            scopes.append(scope)
            entered.set()
            await auth.access_token()

    async with auth.lock:
        task = asyncio.create_task(queued())
        await entered.wait()
        await anyio.sleep(0)
        if mode == "anyio":
            scopes[0].cancel()
            await task
        else:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    assert calls == [] and vault.reads == vault.deletes == vault.releases == 0
    assert vault.credential == vault.original and auth.tokens is None
    assert_private_output_absent(capsys, caplog)


@pytest.mark.parametrize("mode", ["asyncio", "anyio"])
async def test_cancel_pending_after_saved_successor_preserves_rotation_and_propagates(mode, capsys, caplog):
    calls = []
    scopes = []
    propagated = []

    def cancel_after_save():
        if mode == "anyio":
            scopes[0].cancel()
        else:
            asyncio.current_task().cancel()

    vault = ConsumerVault(on_saved=cancel_after_save)
    tokens = Tokens(PRIVATE + "-access", PRIVATE + "-successor", time.time() + 900)

    async def refresh(value):
        calls.append(value)
        return tokens

    auth = Authorization(SimpleNamespace(refresh=refresh), vault, vault.process_lock)

    async def consume():
        with anyio.CancelScope() as scope:
            scopes.append(scope)
            try:
                await auth.access_token()
            except anyio.get_cancelled_exc_class():
                propagated.append(True)
                raise

    task = asyncio.create_task(consume())
    if mode == "asyncio":
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await task
    assert propagated == [True]
    assert vault.credential.refresh_token == tokens.refresh_token
    assert vault.credential.authorized_until == vault.original.authorized_until
    assert vault.deletes == 0 and len(calls) == 1
    assert auth.tokens == tokens and not vault.held and not auth.lock.locked()
    assert await auth.access_token() == tokens.access_token
    assert len(calls) == 1
    assert_private_output_absent(capsys, caplog)


@pytest.mark.parametrize("delete_failure", [False, True])
async def test_cancellation_during_uncertain_vault_save_preserves_cancellation_and_fences(
    delete_failure, capsys, caplog,
):
    calls = []
    vault = ConsumerVault(delete_failure=delete_failure, write_cancellation=True)

    async def refresh(value):
        calls.append(value)
        return Tokens(PRIVATE + "-access", PRIVATE + "-successor", time.time() + 900)

    auth = Authorization(SimpleNamespace(refresh=refresh), vault, vault.process_lock)
    with pytest.raises(asyncio.CancelledError) as error:
        await auth.access_token()
    assert error.value is vault.write_error
    assert vault.deletes == 1 and auth.tokens is None and auth.authorized_until is None
    assert not vault.held and not auth.lock.locked()
    with pytest.raises(ConnectorError, match="Sign in"):
        await auth.access_token()
    assert len(calls) == 1
    assert_private_output_absent(capsys, caplog)


async def test_cleanup_failure_error_is_private_and_explicit_new_signin_clears_local_fence(capsys, caplog):
    calls = []
    vault = ConsumerVault(delete_failure=True)

    async def refresh(value):
        calls.append(value)
        raise RuntimeError(PRIVATE)

    auth = Authorization(SimpleNamespace(refresh=refresh), vault, vault.process_lock)
    with pytest.raises(ConnectorError, match="no operation was retried") as error:
        await auth.access_token()
    assert PRIVATE not in str(error.value)
    with pytest.raises(ConnectorError, match="Sign in"):
        await auth.access_token()
    assert len(calls) == 1
    tokens = Tokens(PRIVATE + "-new-access", PRIVATE + "-new-refresh", time.time() + 900)
    await auth.remember(tokens, time.time() + 3000)
    assert await auth.access_token() == tokens.access_token
    assert len(calls) == 1 and vault.deletes == 1
    assert_private_output_absent(capsys, caplog)


async def test_separate_signin_saved_in_vault_recovers_existing_consumer_after_failed_cleanup(
    capsys, caplog,
):
    entered = asyncio.Event()
    calls = []
    vault = ConsumerVault(delete_failure=True)
    replacement = Credential(PRIVATE + "-independent-signin", time.time() + 7000)
    tokens = Tokens(PRIVATE + "-fresh-access", PRIVATE + "-fresh-successor", time.time() + 900)

    async def refresh(value):
        calls.append(value)
        if value == vault.original.refresh_token:
            entered.set()
            await asyncio.Event().wait()
        assert value == replacement.refresh_token
        return tokens

    auth = Authorization(SimpleNamespace(refresh=refresh), vault, vault.process_lock)
    await cancelled_consumer(auth, entered, "asyncio")
    with pytest.raises(ConnectorError, match="Sign in"):
        await auth.access_token()
    assert calls == [vault.original.refresh_token]
    # Missing and unreadable vault outcomes must not erase the old-value fence.
    vault.credential = None
    with pytest.raises(ConnectorError, match="Sign in"):
        await auth.access_token()
    saved_read = vault.read

    def unreadable():
        raise ConnectorError("Cannot read Windows Credential Manager.")

    vault.read = unreadable
    with pytest.raises(ConnectorError, match="Cannot read"):
        await auth.access_token()
    vault.read = saved_read
    vault.credential = vault.original
    with pytest.raises(ConnectorError, match="Sign in"):
        await auth.access_token()
    assert calls == [vault.original.refresh_token]
    # Model a separate CLI process completing sign-in under the shared native lock.
    async with vault.process_lock():
        vault.write(replacement)
    assert await auth.access_token() == tokens.access_token
    assert calls == [vault.original.refresh_token, replacement.refresh_token]
    assert vault.credential.refresh_token == tokens.refresh_token
    assert vault.credential.authorized_until == replacement.authorized_until
    assert vault.deletes == 1
    assert_private_output_absent(capsys, caplog)


@pytest.mark.parametrize("refresh_cancelled", [False, True])
async def test_cancellation_from_cleanup_is_not_swallowed_and_still_fences_replay(
    refresh_cancelled, capsys, caplog,
):
    calls = []
    vault = ConsumerVault(delete_cancellation=True)

    async def refresh(value):
        calls.append(value)
        if refresh_cancelled:
            raise asyncio.CancelledError("synthetic refresh cancellation")
        raise RuntimeError(PRIVATE)

    auth = Authorization(SimpleNamespace(refresh=refresh), vault, vault.process_lock)
    with pytest.raises(asyncio.CancelledError) as error:
        await auth.access_token()
    assert error.value is vault.delete_error
    assert vault.deletes == 1 and auth.tokens is None and auth.authorized_until is None
    assert not vault.held and not auth.lock.locked()
    with pytest.raises(ConnectorError, match="Sign in"):
        await auth.access_token()
    assert len(calls) == 1
    assert_private_output_absent(capsys, caplog)


async def test_cancelled_uncertain_refresh_never_dispatches_the_resource_request(capsys, caplog):
    entered = asyncio.Event()
    refreshes = []
    dispatched = []
    vault = ConsumerVault()

    async def refresh(value):
        refreshes.append(value)
        entered.set()
        await asyncio.Event().wait()

    auth = Authorization(SimpleNamespace(refresh=refresh), vault, vault.process_lock)

    def resource(request):
        dispatched.append(request)
        return httpx2.Response(200)

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(resource),
        auth=ResourceBearerAuth(Config("https://app.test"), auth),
    ) as http:
        task = asyncio.create_task(http.post("https://app.test/mcp", json={}))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ConnectorError, match="Sign in"):
            await http.post("https://app.test/mcp", json={})
    assert len(refreshes) == 1 and dispatched == [] and vault.deletes == 1
    assert_private_output_absent(capsys, caplog)


@pytest.mark.parametrize("acquired", [False, True])
@pytest.mark.parametrize("mode", ["asyncio", "anyio"])
async def test_windows_mutex_wait_or_held_refresh_cancellation_releases_only_owned_handle(
    acquired, mode, monkeypatch, capsys, caplog,
):
    entered = asyncio.Event()
    calls = []
    handle = object()
    api = SimpleNamespace(CloseHandle=lambda value: calls.append(("close", value)))

    def wait(value, timeout):
        assert value is handle and timeout == 0
        entered.set()
        return 0 if acquired else 258

    events = SimpleNamespace(CreateMutex=lambda *_args: handle, WaitForSingleObject=wait,
                             WAIT_OBJECT_0=0, WAIT_ABANDONED=128,
                             ReleaseMutex=lambda value: calls.append(("release", value)))
    monkeypatch.setitem(sys.modules, "win32api", api)
    monkeypatch.setitem(sys.modules, "win32event", events)
    vault = ConsumerVault()
    # This lock adapter is mocked; it never opens a real named Windows mutex.
    lock = WindowsCredentialLock("synthetic-refresh-mutex-only")

    async def refresh(value):
        vault.held = True
        await asyncio.Event().wait()

    auth = Authorization(SimpleNamespace(refresh=refresh), vault, lock)
    # ConsumerVault normally verifies its own lock; adapt reads to this mocked one.
    vault.read = lambda: vault.credential
    await cancelled_consumer(auth, entered, mode)
    assert calls == ([("release", handle), ("close", handle)] if acquired else [("close", handle)])
    assert vault.deletes == (1 if acquired else 0)
    assert vault.credential == (None if acquired else vault.original)
    assert not auth.lock.locked()
    assert_private_output_absent(capsys, caplog)
