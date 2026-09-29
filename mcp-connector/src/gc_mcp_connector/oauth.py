"""Browser authorization for the pre-registered Global Connects desktop client."""

import base64
import hashlib
import hmac
import json
import queue
import secrets
import socket
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlencode, urlsplit

import anyio
import httpx2

from .config import CLIENT_ID, REDIRECT_URI, SCOPES, Config, ConnectorError


@dataclass(frozen=True, repr=False)
class AuthorizationAttempt:
    state: str
    verifier: str

    @classmethod
    def create(cls) -> "AuthorizationAttempt":
        return cls(secrets.token_urlsafe(32), secrets.token_urlsafe(64))

    @property
    def challenge(self) -> str:
        return (
            base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )


@dataclass(frozen=True, repr=False)
class Tokens:
    access_token: str
    refresh_token: str
    expires_at: float


async def json_request(client: httpx2.AsyncClient, method: str, url: str, **kwargs) -> dict:
    """Bound metadata/token bodies and suppress all raw HTTP failure output."""
    try:
        async with client.stream(method, url, follow_redirects=False, **kwargs) as response:
            if response.status_code != 200:
                raise ConnectorError(
                    "Authorization was unavailable or denied. Sign in again if authorization expired."
                )
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 64 * 1024:
                    raise ConnectorError("Authorization response exceeded its permitted size.")
            result = json.loads(body)
            if not isinstance(result, dict):
                raise ValueError
            return result
    except ConnectorError:
        raise
    except (httpx2.HTTPError, ValueError, UnicodeError):
        raise ConnectorError(
            "The authorization request did not complete safely. Try signing in again."
        ) from None


class OAuthClient:
    def __init__(self, config: Config, client: httpx2.AsyncClient) -> None:
        self.config, self.client = config, client

    async def discover(self) -> None:
        resource = await json_request(
            self.client, "GET", f"{self.config.origin}/.well-known/oauth-protected-resource/mcp"
        )
        # The SDK's AnyHttpUrl normalizes an origin-only issuer with a trailing
        # slash. Accept that exact equivalent, never an arbitrary issuer path.
        if resource.get("resource") != self.config.resource or resource.get(
            "authorization_servers"
        ) not in ([self.config.origin], [self.config.origin + "/"]):
            raise ConnectorError(
                "Application resource metadata does not match the configured origin."
            )
        metadata = await json_request(
            self.client, "GET", f"{self.config.origin}/.well-known/oauth-authorization-server"
        )
        expected = {
            "issuer": self.config.origin,
            "authorization_endpoint": f"{self.config.origin}/oauth/mcp/authorize",
            "token_endpoint": f"{self.config.origin}/oauth/mcp/token",
        }
        if any(metadata.get(key) != value for key, value in expected.items()):
            raise ConnectorError(
                "Authorization metadata must use the configured application endpoints."
            )
        if "S256" not in metadata.get("code_challenge_methods_supported", []):
            raise ConnectorError("The application must support S256 PKCE.")

    def authorization_url(self, attempt: AuthorizationAttempt, scopes: list[str]) -> str:
        if not scopes or set(scopes) - SCOPES:
            raise ConnectorError("Select supported MCP capabilities.")
        query = urlencode(
            {
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "resource": self.config.resource,
                "response_type": "code",
                "code_challenge_method": "S256",
                "code_challenge": attempt.challenge,
                "state": attempt.state,
                "scope": " ".join(sorted(set(scopes))),
            }
        )
        return f"{self.config.origin}/oauth/mcp/authorize?{query}"

    async def exchange(self, code: str, attempt: AuthorizationAttempt) -> Tokens:
        return await self._tokens(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": attempt.verifier,
                "redirect_uri": REDIRECT_URI,
            }
        )

    async def refresh(self, refresh_token: str) -> Tokens:
        return await self._tokens({"grant_type": "refresh_token", "refresh_token": refresh_token})

    async def _tokens(self, form: dict[str, str]) -> Tokens:
        body = await json_request(
            self.client,
            "POST",
            f"{self.config.origin}/oauth/mcp/token",
            data={**form, "client_id": CLIENT_ID, "resource": self.config.resource},
        )
        access, refresh, expires = (
            body.get("access_token"),
            body.get("refresh_token"),
            body.get("expires_in"),
        )
        if (
            str(body.get("token_type", "")).lower() != "bearer"
            or not isinstance(access, str)
            or not isinstance(refresh, str)
            or not 20 <= len(access) <= 512
            or not 20 <= len(refresh) <= 512
            or any(ord(char) <= 32 or ord(char) >= 127 for char in access + refresh)
            or type(expires) is not int
            or not 1 <= expires <= 900
        ):
            raise ConnectorError("The application returned an invalid authorization credential.")
        return Tokens(access, refresh, time.time() + expires)


def callback_code(path: str, attempt: AuthorizationAttempt, issuer: str) -> str:
    if len(path) > 4096:
        raise ValueError("Invalid callback")
    parsed = urlsplit(path)
    if parsed.path != "/callback" or parsed.scheme or parsed.netloc or parsed.fragment:
        raise ValueError("Invalid callback")
    pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=8)
    params = dict(pairs)
    state = params.get("state", "")
    if (
        len(params) != len(pairs)
        or not state.isascii()
        or not hmac.compare_digest(state, attempt.state)
    ):
        raise ValueError("Invalid callback state")
    if params.get("iss", issuer) != issuer:
        raise ValueError("Invalid callback issuer")
    if "error" in params:
        raise ConnectorError("Browser authorization was declined. No connection was saved.")
    code = params.get("code", "")
    if not 20 <= len(code) <= 512 or any(ord(char) <= 32 or ord(char) >= 127 for char in code):
        raise ValueError("Invalid callback code")
    return code


class CallbackServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address: tuple[str, int], attempt: AuthorizationAttempt, issuer: str):
        self.attempt, self.issuer = attempt, issuer
        self.result: queue.Queue[str | ConnectorError] = queue.Queue(maxsize=1)
        self.accepted = threading.Event()
        self.accept_lock = threading.Lock()
        super().__init__(address, CallbackHandler)

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address


class CallbackHandler(BaseHTTPRequestHandler):
    server: CallbackServer

    def log_message(self, *_args) -> None:
        # BaseHTTPRequestHandler would otherwise print the authorization code URL.
        pass

    def do_GET(self) -> None:
        try:
            if self.headers.get_all("Host") != [f"127.0.0.1:{self.server.server_port}"]:
                raise ValueError
            result: str | ConnectorError = callback_code(
                self.path, self.server.attempt, self.server.issuer
            )
        except ConnectorError as exc:
            result = exc
        except ValueError:
            self._respond(400, "Invalid authorization callback.")
            return
        with self.server.accept_lock:
            if self.server.accepted.is_set():
                self._respond(409, "This authorization callback has already been received.")
                return
            self.server.accepted.set()
            self.server.result.put_nowait(result)
        self._respond(
            200, "Authorization response received. Return to Global Connects connector to finish."
        )

    def _respond(self, status: int, message: str) -> None:
        payload = message.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(payload)


async def browser_code(oauth: OAuthClient, attempt: AuthorizationAttempt, scopes: list[str]) -> str:
    # Bind before opening the browser: a port conflict must fail before authorization begins.
    try:
        server = CallbackServer(("127.0.0.1", 8765), attempt, oauth.config.origin)
    except OSError:
        raise ConnectorError(
            "Cannot listen on 127.0.0.1:8765. Close the other sign-in attempt and retry."
        ) from None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if not webbrowser.open(oauth.authorization_url(attempt, scopes), new=1):
            raise ConnectorError("A browser could not be opened for sign-in.")
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            try:
                result = server.result.get_nowait()
            except queue.Empty:
                await anyio.sleep(0.1)
                continue
            if isinstance(result, ConnectorError):
                raise result
            return result
        raise ConnectorError("Browser sign-in timed out; run sign-in again.")
    finally:
        await anyio.to_thread.run_sync(server.shutdown)
        server.server_close()
        thread.join(timeout=2)
