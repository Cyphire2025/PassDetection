"""Real isolated loopback listeners around the sign-in consumer; no browser or vault."""

import argparse
import asyncio
import socket
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

import anyio
import pytest

from gc_mcp_connector import cli, oauth
from gc_mcp_connector.config import ConnectorError


@pytest.fixture
def sign_in(monkeypatch, capsys, caplog):
    original_server = oauth.CallbackServer
    servers = []
    target = SimpleNamespace(port=0)
    attempt = oauth.AuthorizationAttempt.create()
    code = "synthetic-authorization-code-never-exchanged"
    vault = SimpleNamespace(read=Mock(return_value=None), write=Mock(), delete=Mock())
    exchange = AsyncMock(side_effect=AssertionError("Unexpected token exchange"))
    discover = AsyncMock()
    opened = threading.Event()

    class ObservedServer(original_server):
        def __init__(self, address, current_attempt, issuer):
            assert address == ("127.0.0.1", 8765)
            self.listener_thread = None
            self.started = threading.Event()
            super().__init__(("127.0.0.1", target.port), current_attempt, issuer)
            servers.append(self)

        def serve_forever(self, poll_interval=0.5):
            self.listener_thread = threading.current_thread()
            self.started.set()
            super().serve_forever(poll_interval=poll_interval)

    def open_browser(url, *, new):
        # The consumer must bind and start before invoking the browser opener.
        assert new == 1 and servers[-1].started.wait(timeout=2)
        assert servers[-1].socket.getsockname()[0] == "127.0.0.1"
        assert parse_qs(urlsplit(url).query)["state"] == [attempt.state]
        opened.set()
        return True

    browser = Mock(side_effect=open_browser)
    monkeypatch.setattr(oauth, "CallbackServer", ObservedServer)
    monkeypatch.setattr(oauth.webbrowser, "open", browser)
    monkeypatch.setattr(oauth.AuthorizationAttempt, "create", lambda: attempt)
    monkeypatch.setattr(oauth.OAuthClient, "discover", discover)
    monkeypatch.setattr(oauth.OAuthClient, "exchange", exchange)
    monkeypatch.setattr(cli, "WindowsVault", lambda _key: vault)
    monkeypatch.setattr(cli, "WindowsCredentialLock", lambda _key: None)

    async def forbid_network(*_args, **_kwargs):
        pytest.fail("Lifecycle tests must not contact an application or token endpoint")

    monkeypatch.setattr(oauth.httpx2.AsyncHTTPTransport, "handle_async_request", forbid_network)
    args = argparse.Namespace(
        origin="https://application.invalid", command="sign-in", scopes=["mcp:read"]
    )

    def assert_closed():
        assert len(servers) == 1
        server = servers[0]
        assert server.listener_thread is not None and not server.listener_thread.is_alive()
        assert server.socket.fileno() == -1
        with original_server(("127.0.0.1", server.server_port), attempt, args.origin):
            pass  # A fresh exclusive listener can bind immediately.

    def callback(**params):
        url = f"http://127.0.0.1:{servers[-1].server_port}/callback?" + urlencode(params)
        with urlopen(url, timeout=2) as response:
            assert response.status == 200
            body = response.read().decode()
            assert code not in body and attempt.state not in body

    yield SimpleNamespace(
        args=args,
        attempt=attempt,
        code=code,
        target=target,
        servers=servers,
        browser=browser,
        open_browser=open_browser,
        opened=opened,
        exchange=exchange,
        discover=discover,
        vault=vault,
        assert_closed=assert_closed,
        callback=callback,
    )
    # If a regression leaks a listener, still release this test's private port.
    for server in servers:
        if server.listener_thread is not None and server.listener_thread.is_alive():
            server.shutdown()
            server.listener_thread.join(timeout=2)
        server.server_close()
    exchange.assert_not_awaited()
    vault.write.assert_not_called()
    vault.delete.assert_not_called()
    captured = capsys.readouterr()
    output = captured.out + captured.err + caplog.text
    assert all(value not in output for value in (attempt.state, attempt.verifier, code))


async def test_sign_in_deadline_releases_listener_without_exchange(sign_in, monkeypatch):
    f = sign_in
    observed = []
    samples = iter([500.0, 799.9, 800.0])

    def clock():
        value = next(samples)
        observed.append(value)
        return value

    # Replace only oauth's clock reference, not asyncio's real monotonic clock.
    monkeypatch.setattr(oauth, "time", SimpleNamespace(monotonic=clock))
    with pytest.raises(ConnectorError, match="Browser sign-in timed out"):
        await cli.run(f.args)
    assert observed == [500.0, 799.9, 800.0]  # Original absolute 300-second deadline.
    f.browser.assert_called_once()
    f.assert_closed()


@pytest.mark.parametrize("timing", ["before_callback", "callback_queued", "during_cleanup"])
async def test_sign_in_cancel_scope_releases_listener_without_exchange(sign_in, timing):
    f = sign_in
    with anyio.CancelScope() as scope:

        def cancel_on_open(url, *, new):
            f.open_browser(url, new=new)
            if timing != "before_callback":
                f.callback(state=f.attempt.state, code=f.code)
            if timing == "during_cleanup":
                asyncio.get_running_loop().call_soon(scope.cancel)
            else:
                scope.cancel()
            return True

        f.browser.side_effect = cancel_on_open
        await cli.run(f.args)
    assert scope.cancelled_caught
    f.assert_closed()


async def test_sign_in_task_cancellation_releases_listener_without_exchange(sign_in):
    f = sign_in
    task = asyncio.create_task(cli.run(f.args))
    try:
        with anyio.fail_after(3):
            while not f.opened.is_set():
                await anyio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        f.assert_closed()
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


@pytest.mark.parametrize("failure", [False, OSError("synthetic browser unavailable")])
async def test_browser_open_failure_releases_listener_without_exchange(sign_in, failure):
    f = sign_in

    def fail_open(url, *, new):
        f.open_browser(url, new=new)
        if isinstance(failure, Exception):
            raise failure
        return failure

    f.browser.side_effect = fail_open
    expected = OSError if isinstance(failure, Exception) else ConnectorError
    with pytest.raises(expected):
        await cli.run(f.args)
    f.assert_closed()


async def test_occupied_callback_port_never_opens_browser_or_exchanges(sign_in):
    f = sign_in
    with socket.socket() as occupied:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        f.target.port = occupied.getsockname()[1]
        with pytest.raises(ConnectorError, match="Cannot listen on 127.0.0.1:8765"):
            await cli.run(f.args)
        f.browser.assert_not_called()
        assert not f.servers
        assert occupied.fileno() != -1  # The unrelated existing listener is preserved.


async def test_browser_denial_releases_listener_without_exchanging_or_logging(sign_in):
    f = sign_in

    def decline(url, *, new):
        f.open_browser(url, new=new)
        f.callback(state=f.attempt.state, error="access_denied")
        return True

    f.browser.side_effect = decline
    with pytest.raises(ConnectorError, match="declined"):
        await cli.run(f.args)
    f.assert_closed()


async def test_browser_code_success_closes_listener_before_returning_code(sign_in):
    f = sign_in

    def approve(url, *, new):
        f.open_browser(url, new=new)
        f.callback(state=f.attempt.state, code=f.code)
        return True

    f.browser.side_effect = approve
    client = oauth.OAuthClient(cli.Config(f.args.origin), None)
    assert await oauth.browser_code(client, f.attempt, f.args.scopes) == f.code
    f.assert_closed()
