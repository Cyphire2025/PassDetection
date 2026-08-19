from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.config.settings import Settings
from app.presentation.api.v1.routes.health import readiness


class _HealthyDatabase:
    async def execute(self, _statement: object) -> None:
        return None


@pytest.mark.asyncio
async def test_required_realtime_outage_is_visible_and_fails_readiness() -> None:
    settings = Settings(
        app_secret_key="unit-test-secret",
        app_env="development",
        processing_backend="background",
        _env_file=None,
    )
    with (
        patch("app.presentation.api.v1.routes.health.get_ai_priority_coordinator") as coordinator,
        patch(
            "app.presentation.api.v1.routes.health.gemini_configuration_readiness",
            return_value=({}, True),
        ),
        patch(
            "app.presentation.api.v1.routes.health.gemini_worker_readiness",
            return_value=({}, True),
        ),
        patch(
            "app.presentation.api.v1.routes.health.email_runtime_readiness",
            return_value=({}, True),
        ),
        patch(
            "app.presentation.api.v1.routes.health.get_mobile_realtime_hub",
            return_value=SimpleNamespace(readiness=lambda: ("unreachable_required", False)),
        ),
    ):
        coordinator.return_value.snapshot.return_value = object()
        response = await readiness(
            db=_HealthyDatabase(),  # type: ignore[arg-type]
            settings=settings,
        )

    assert response.status_code == 503
    assert b'"mobile_realtime":"unreachable_required"' in response.body


@pytest.mark.asyncio
async def test_explicit_cursor_fallback_is_visible_without_false_outage() -> None:
    settings = Settings(
        app_secret_key="unit-test-secret",
        app_env="development",
        processing_backend="background",
        _env_file=None,
    )
    with (
        patch("app.presentation.api.v1.routes.health.get_ai_priority_coordinator") as coordinator,
        patch(
            "app.presentation.api.v1.routes.health.gemini_configuration_readiness",
            return_value=({}, True),
        ),
        patch(
            "app.presentation.api.v1.routes.health.gemini_worker_readiness",
            return_value=({}, True),
        ),
        patch(
            "app.presentation.api.v1.routes.health.email_runtime_readiness",
            return_value=({}, True),
        ),
        patch(
            "app.presentation.api.v1.routes.health.get_mobile_realtime_hub",
            return_value=SimpleNamespace(readiness=lambda: ("degraded_cursor_fallback", True)),
        ),
    ):
        coordinator.return_value.snapshot.return_value = object()
        response = await readiness(
            db=_HealthyDatabase(),  # type: ignore[arg-type]
            settings=settings,
        )

    assert response.status_code == 200
    assert b'"mobile_realtime":"degraded_cursor_fallback"' in response.body
