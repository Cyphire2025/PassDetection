from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.core.config.settings import Settings
from app.infrastructure.runtime_readiness import RuntimeReadinessProbe


class _ScalarView:
    def __init__(self, values: tuple[str, ...]) -> None:
        self._values = values

    def all(self) -> tuple[str, ...]:
        return self._values


class _ScalarResult:
    def __init__(self, values: tuple[str, ...]) -> None:
        self._values = values

    def scalars(self) -> _ScalarView:
        return _ScalarView(self._values)


class _MappingView:
    def __init__(self, row: dict[str, int]) -> None:
        self._row = row

    def one(self) -> dict[str, int]:
        return self._row


class _MappingResult:
    def __init__(self, row: dict[str, int]) -> None:
        self._row = row

    def mappings(self) -> _MappingView:
        return _MappingView(self._row)


class _Database:
    def __init__(
        self,
        *,
        versions: tuple[str, ...] = ("0088_merge_my_photos_hardening",),
        due_count: int = 0,
        blocked_count: int = 0,
        oldest_due_seconds: int = 0,
    ) -> None:
        self._versions = versions
        self._cleanup = {
            "due_count": due_count,
            "blocked_count": blocked_count,
            "oldest_due_seconds": oldest_due_seconds,
        }

    async def execute(self, statement: object) -> object:
        sql = str(statement)
        if "alembic_version" in sql:
            return _ScalarResult(self._versions)
        if "storage_cleanup_jobs" in sql:
            return _MappingResult(self._cleanup)
        raise AssertionError(f"Unexpected readiness query: {sql}")


def _settings() -> Settings:
    return Settings(
        app_secret_key="runtime-readiness-test-secret",
        app_env="development",
        processing_backend="background",
        _env_file=None,
    )


@pytest.mark.asyncio
async def test_ready_snapshot_requires_schema_storage_and_core_dependencies() -> None:
    probe = RuntimeReadinessProbe(cache_seconds=30)
    with patch(
        "app.infrastructure.runtime_readiness._probe_object_storage",
        return_value=True,
    ):
        snapshot = await probe.snapshot(
            db=_Database(),  # type: ignore[arg-type]
            settings=_settings(),
        )

    assert snapshot.core_ready is True
    assert snapshot.checks["database_schema"] == "compatible"
    assert snapshot.checks["object_storage"] == "available"
    assert snapshot.checks["malware_scanner"] == "development_bypass"
    assert snapshot.capabilities["storage_cleanup"]["available"] is True
    assert snapshot.capabilities["my_photos"]["required"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("versions", "expected_status"),
    [
        ((), "missing"),
        (("0087_enterprise_hardening",), "revision_mismatch"),
        (
            ("0086_my_photos_foundation", "0087_enterprise_hardening"),
            "multiple_heads",
        ),
    ],
)
async def test_schema_drift_fails_readiness_closed(
    versions: tuple[str, ...],
    expected_status: str,
) -> None:
    probe = RuntimeReadinessProbe(cache_seconds=30)
    with patch(
        "app.infrastructure.runtime_readiness._probe_object_storage",
        return_value=True,
    ):
        snapshot = await probe.snapshot(
            db=_Database(versions=versions),  # type: ignore[arg-type]
            settings=_settings(),
        )

    assert snapshot.core_ready is False
    assert snapshot.checks["database_schema"] == expected_status
    assert snapshot.capabilities["database_schema"]["traffic_gate"] is True


@pytest.mark.asyncio
async def test_slow_network_probes_are_cached_by_configuration() -> None:
    probe = RuntimeReadinessProbe(cache_seconds=30)
    with patch(
        "app.infrastructure.runtime_readiness._probe_object_storage",
        return_value=True,
    ) as storage_probe:
        first = await probe.snapshot(
            db=_Database(),  # type: ignore[arg-type]
            settings=_settings(),
        )
        second = await probe.snapshot(
            db=_Database(),  # type: ignore[arg-type]
            settings=_settings(),
        )

    assert first.core_ready is True
    assert second.core_ready is True
    storage_probe.assert_called_once_with()


@pytest.mark.asyncio
async def test_cleanup_backlog_is_visible_without_causing_an_api_outage() -> None:
    probe = RuntimeReadinessProbe(cache_seconds=30)
    with patch(
        "app.infrastructure.runtime_readiness._probe_object_storage",
        return_value=True,
    ):
        snapshot = await probe.snapshot(
            db=_Database(blocked_count=3),  # type: ignore[arg-type]
            settings=_settings(),
        )

    assert snapshot.core_ready is True
    assert snapshot.checks["storage_cleanup_backlog"] == "blocked_jobs:3"
    cleanup = snapshot.capabilities["storage_cleanup"]
    assert cleanup["available"] is False
    assert cleanup["traffic_gate"] is False


@pytest.mark.asyncio
async def test_dependency_probe_timeout_is_cached_and_fails_core_closed() -> None:
    probe = RuntimeReadinessProbe(
        cache_seconds=30,
        refresh_timeout_seconds=0.001,
    )

    async def _never_ready(_settings: Settings) -> object:
        await asyncio.sleep(1)
        raise AssertionError("cancelled readiness refresh must not complete")

    with patch(
        "app.infrastructure.runtime_readiness._refresh_blocking_capabilities",
        side_effect=_never_ready,
    ) as refresh:
        first = await probe.snapshot(
            db=_Database(),  # type: ignore[arg-type]
            settings=_settings(),
        )
        second = await probe.snapshot(
            db=_Database(),  # type: ignore[arg-type]
            settings=_settings(),
        )

    assert first.core_ready is False
    assert first.checks["object_storage"] == "probe_timeout"
    assert second.checks == first.checks
    refresh.assert_called_once()
