"""Service-test connection setup preserves structured credentials without connecting."""

from __future__ import annotations

import importlib

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from tests.postgresql_connection import service_test_url


@pytest.mark.parametrize(
    ("username", "password", "host", "port"),
    [
        ("synthetic", "simple-password", "localhost", "5432"),
        ("synthetic", "test:p@ss/word#?%", "localhost", "5432"),
        ("test@user", "synthetic-only", "localhost", "55432"),
        ("synthetic", "simple-password", "::1", "5432"),
    ],
)
async def test_connection_fields_survive_driver_construction(
    monkeypatch, username, password, host, port
):
    values = {
        "POSTGRES_USER": username,
        "POSTGRES_PASSWORD": password,
        "POSTGRES_HOST": host,
        "POSTGRES_PORT": port,
        "POSTGRES_DB": "passdetection_ci_url_probe",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    address = service_test_url()
    assert make_url(address.render_as_string(hide_password=False)) == address
    assert password not in str(address)
    engine = create_async_engine(address)
    try:
        assert engine.url.username == username
        assert engine.url.password == password
        assert engine.url.host == host
        assert engine.url.port == int(port)
        assert engine.url.database == values["POSTGRES_DB"]
    finally:
        await engine.dispose()


def test_connection_defaults_and_missing_required_fields(monkeypatch):
    monkeypatch.setenv("POSTGRES_USER", "synthetic")
    monkeypatch.setenv("POSTGRES_PASSWORD", "synthetic-only")
    monkeypatch.setenv("POSTGRES_DB", "passdetection_ci_url_probe")
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    monkeypatch.delenv("POSTGRES_PORT", raising=False)
    assert (service_test_url().host, service_test_url().port) == ("localhost", 5432)
    monkeypatch.delenv("POSTGRES_PASSWORD")
    with pytest.raises(KeyError, match="POSTGRES_PASSWORD"):
        service_test_url()


@pytest.mark.parametrize(
    "module_name",
    [
        "tests.service_integration.test_real_service_contracts",
        "tests.service_integration.test_my_photos_postgresql_contracts",
    ],
)
def test_actual_service_suites_use_the_shared_builder(module_name):
    assert importlib.import_module(module_name)._postgres_url is service_test_url
