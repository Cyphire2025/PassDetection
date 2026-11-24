"""Relocated readiness policy guards and public annotation/alias contracts."""

from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import get_type_hints
from unittest.mock import Mock

import pytest

from app.core.config.settings import Settings
from app.infrastructure import (
    runtime_readiness,
)
from app.infrastructure import (
    runtime_readiness_capabilities as capabilities,
)
from app.infrastructure import (
    runtime_readiness_contracts as contracts,
)
from app.infrastructure import (
    runtime_readiness_database as database,
)
from app.infrastructure import (
    runtime_readiness_probes as probes,
)


def settings(**changes):
    return Settings(
        app_secret_key="synthetic-readiness-policy-test-secret",
        app_env="development",
        dashboard_rate_limit_require_redis=False,
        login_lockout_require_redis=False,
        public_upload_rate_limit_require_redis=False,
        _env_file=None,
    ).model_copy(update=changes)


def test_original_facade_aliases_resolve_real_owners_and_runtime_annotations():
    modules = (contracts, database, probes, capabilities)
    for owner in modules:
        for name, value in vars(owner).items():
            if getattr(value, "__module__", "") == owner.__name__:
                assert getattr(runtime_readiness, name) is value
                if inspect.isfunction(value) or inspect.isclass(value):
                    get_type_hints(value)
        assert not hasattr(owner, "_runtime_probe")
    assert isinstance(runtime_readiness._runtime_probe, runtime_readiness.RuntimeReadinessProbe)
    assert (
        get_type_hints(runtime_readiness.RuntimeReadinessProbe.snapshot)["return"]
        is contracts.RuntimeCapabilitySnapshot
    )
    assert (
        get_type_hints(runtime_readiness.RuntimeReadinessProbe._blocking_snapshot)["return"]
        is contracts._BlockingSnapshot
    )
    assert (
        get_type_hints(runtime_readiness.runtime_capability_readiness)["return"]
        is contracts.RuntimeCapabilitySnapshot
    )


@pytest.mark.asyncio
async def test_cache_reuses_object_until_exact_ttl_or_configuration_change(monkeypatch):
    clock = [10.0]
    calls = []

    async def refresh(configuration):
        result = capabilities._timed_out_snapshot(configuration)
        calls.append(result)
        return result

    monkeypatch.setattr(runtime_readiness, "_refresh_blocking_capabilities", refresh)
    probe = runtime_readiness.RuntimeReadinessProbe(clock=lambda: clock[0], cache_seconds=15)
    configuration = settings()
    first = await probe._blocking_snapshot(configuration)
    assert await probe._blocking_snapshot(configuration) is first
    assert calls == [first]
    clock[0] = 25.0
    expired = await probe._blocking_snapshot(configuration)
    assert expired is not first and calls == [first, expired]
    changed = await probe._blocking_snapshot(
        configuration.model_copy(update={"app_env": "staging"})
    )
    assert changed is not expired and calls == [first, expired, changed]


@pytest.mark.parametrize("value", [None, (), ("ok", "true"), (True, True), ("ok", True, "extra")])
def test_malformed_probe_result_never_claims_dependency_ready(value):
    assert capabilities._probe_result(value, failure_status="probe_failed") == (
        "probe_failed",
        False,
    )


def test_disabled_document_ingestion_does_not_contact_scanner(monkeypatch):
    factory = Mock(side_effect=AssertionError("disabled ingestion must not open a scanner"))
    monkeypatch.setattr(probes, "malware_scanner_from_settings", factory)
    assert probes._probe_malware_scanner(settings(untrusted_document_ingestion_enabled=False)) == (
        "not_required_ingestion_disabled",
        True,
    )
    factory.assert_not_called()


def test_non_development_ingestion_requires_real_configured_scanner(monkeypatch):
    monkeypatch.setattr(probes, "malware_scanner_from_settings", lambda _: object())
    assert probes._probe_malware_scanner(
        settings(
            app_env="production",
            untrusted_document_ingestion_enabled=True,
        )
    ) == ("not_configured", False)


def test_configured_scanner_health_is_checked_without_network_fixture(monkeypatch):
    class Scanner:
        healthcheck = Mock()

    scanner = Scanner()
    monkeypatch.setattr(probes, "ClamAVMalwareScanner", Scanner)
    monkeypatch.setattr(probes, "malware_scanner_from_settings", lambda _: scanner)
    assert probes._probe_malware_scanner(
        settings(
            app_env="production",
            untrusted_document_ingestion_enabled=True,
        )
    ) == ("available", True)
    scanner.healthcheck.assert_called_once_with()


@pytest.mark.parametrize("outcome", [True, False, ConnectionError("synthetic Redis outage")])
def test_security_redis_probe_closes_client_for_success_rejection_or_exception(
    monkeypatch, outcome
):
    client = Mock()
    if isinstance(outcome, Exception):
        client.ping.side_effect = outcome
    else:
        client.ping.return_value = outcome
    monkeypatch.setattr(probes.Redis, "from_url", lambda *args, **kwargs: client)
    configuration = settings(dashboard_rate_limit_require_redis=True)
    if isinstance(outcome, Exception):
        with pytest.raises(ConnectionError):
            probes._probe_security_redis(configuration)
    else:
        assert probes._probe_security_redis(configuration) == (
            "available" if outcome else "unreachable",
            outcome,
        )
    client.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_database_probe_errors_report_degradation_without_private_error_text():
    async def fail(_statement):
        raise RuntimeError("synthetic-private-database-diagnostic")

    @asynccontextmanager
    async def savepoint():
        yield

    db = SimpleNamespace(execute=fail, begin_nested=savepoint)
    assert await database._schema_readiness(db, settings()) == ("unavailable", False)
    backlog = await database._cleanup_backlog(db)
    assert backlog == contracts._CleanupBacklog(due_count=0, blocked_count=1, oldest_due_seconds=0)
