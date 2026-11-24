"""CLI recovery with synthetic vault/lock boundaries and no network access."""

import argparse
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from gc_mcp_connector import cli
from gc_mcp_connector.config import Config, ConnectorError


@asynccontextmanager
async def unlocked():
    yield


@pytest.fixture
def vault(monkeypatch):
    value = SimpleNamespace(
        read=Mock(side_effect=ConnectorError("Stored authorization is invalid.")),
        delete=Mock(),
        write=Mock(),
    )
    factory = Mock(return_value=value)
    monkeypatch.setattr(cli, "WindowsVault", factory)
    monkeypatch.setattr(cli, "WindowsCredentialLock", lambda _key: unlocked)
    monkeypatch.setattr(
        cli.httpx2.AsyncHTTPTransport,
        "handle_async_request",
        AsyncMock(side_effect=AssertionError("Network access is forbidden in CLI recovery tests")),
    )
    return value, factory


async def test_forget_can_remove_a_malformed_credential_without_reading_it(vault, capsys):
    value, factory = vault
    await cli.run(argparse.Namespace(origin="https://application.invalid", command="forget"))
    factory.assert_called_once_with(Config("https://application.invalid").credential_key)
    value.read.assert_not_called()
    value.delete.assert_called_once_with()
    value.write.assert_not_called()
    assert "Local authorization cleared" in capsys.readouterr().err


async def test_forget_reports_vault_deletion_failure_without_claiming_success(vault, capsys):
    value, _factory = vault
    value.delete.side_effect = ConnectorError(
        "Cannot clear Windows Credential Manager authorization."
    )
    with pytest.raises(ConnectorError, match="Cannot clear"):
        await cli.run(argparse.Namespace(origin="https://application.invalid", command="forget"))
    value.read.assert_not_called()
    value.delete.assert_called_once_with()
    assert "Local authorization cleared" not in capsys.readouterr().err


async def test_sign_in_still_stops_on_invalid_vault_before_discovery_or_browser(vault, monkeypatch):
    value, _factory = vault
    discover = AsyncMock()
    browser = AsyncMock()
    monkeypatch.setattr(cli.OAuthClient, "discover", discover)
    monkeypatch.setattr(cli, "browser_code", browser)
    with pytest.raises(ConnectorError, match="Stored authorization is invalid"):
        await cli.run(
            argparse.Namespace(
                origin="https://application.invalid", command="sign-in", scopes=["mcp:read"]
            )
        )
    value.read.assert_called_once_with()
    value.delete.assert_not_called()
    discover.assert_not_called()
    browser.assert_not_called()
