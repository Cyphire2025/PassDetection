"""Windows Credential Manager only; never fall back to a file or environment secret."""

import json
import math
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Protocol

import anyio

from .config import ConnectorError


@dataclass(frozen=True, repr=False)
class Credential:
    refresh_token: str
    authorized_until: float


class Vault(Protocol):
    def read(self) -> Credential | None: ...
    def write(self, credential: Credential) -> None: ...
    def delete(self) -> None: ...


class WindowsVault:
    def __init__(self, key: str) -> None:
        if sys.platform != "win32":
            raise ConnectorError("This connector release requires Windows Credential Manager.")
        try:
            import win32cred
        except ImportError:
            raise ConnectorError(
                "Windows Credential Manager is unavailable; install the locked dependencies."
            ) from None
        self.api, self.key = win32cred, key

    def read(self) -> Credential | None:
        try:
            record = self.api.CredRead(self.key, self.api.CRED_TYPE_GENERIC)
        except Exception as exc:
            if getattr(exc, "winerror", None) == 1168:
                return None
            raise ConnectorError("Cannot read Windows Credential Manager.") from None
        try:
            raw = record["CredentialBlob"]
            # pywin32's Unicode CredWrite wrapper accepts text and CredRead
            # returns that credential blob as UTF-16LE bytes.
            body = json.loads(raw.decode("utf-16-le") if isinstance(raw, bytes) else raw)
            if (
                type(body["version"]) is not int
                or body["version"] != 1
                or not isinstance(body["refresh_token"], str)
            ):
                raise ValueError
            if not 20 <= len(body["refresh_token"]) <= 512:
                raise ValueError
            until = float(body["authorized_until"])
            if not math.isfinite(until) or until <= 0:
                raise ValueError
            return Credential(body["refresh_token"], until)
        except (KeyError, TypeError, ValueError, UnicodeError):
            raise ConnectorError(
                "Stored authorization is invalid. Run forget, then sign in again."
            ) from None

    def write(self, credential: Credential) -> None:
        blob = json.dumps(
            {
                "version": 1,
                "refresh_token": credential.refresh_token,
                "authorized_until": credential.authorized_until,
            }
        )
        try:
            self.api.CredWrite(
                {
                    "Type": self.api.CRED_TYPE_GENERIC,
                    "TargetName": self.key,
                    "UserName": "Global Connects MCP",
                    "CredentialBlob": blob,
                    "Persist": self.api.CRED_PERSIST_LOCAL_MACHINE,
                },
                0,
            )
        except Exception:
            raise ConnectorError(
                "Cannot save authorization in Windows Credential Manager."
            ) from None

    def delete(self) -> None:
        try:
            self.api.CredDelete(self.key, self.api.CRED_TYPE_GENERIC, 0)
        except Exception as exc:
            if getattr(exc, "winerror", None) != 1168:
                raise ConnectorError(
                    "Cannot clear Windows Credential Manager authorization."
                ) from None


class WindowsCredentialLock:
    """A session-scoped named mutex serializes rotating credentials across processes."""

    def __init__(self, key: str) -> None:
        self.name = "Local\\" + key.replace(":", "-")

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[None]:
        import win32api
        import win32event

        handle = win32event.CreateMutex(None, False, self.name)
        acquired = False
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                outcome = win32event.WaitForSingleObject(handle, 0)
                if outcome in (win32event.WAIT_OBJECT_0, win32event.WAIT_ABANDONED):
                    acquired = True
                    break
                await anyio.sleep(0.05)
            if not acquired:
                raise ConnectorError(
                    "Another connector is refreshing authorization. Try again shortly."
                )
            yield
        finally:
            if acquired:
                win32event.ReleaseMutex(handle)
            win32api.CloseHandle(handle)
