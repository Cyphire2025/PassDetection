from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.infrastructure.email import beat_healthcheck as health


@pytest.mark.parametrize("email_enabled", [True, False])
@pytest.mark.parametrize("heartbeat_ready", [True, False])
def test_health_checks_the_active_scheduler_path(monkeypatch, email_enabled, heartbeat_ready):
    settings = SimpleNamespace(email_integrations_enabled=email_enabled)
    monkeypatch.setattr(health, "get_settings", lambda: settings)
    probe = Mock(return_value=heartbeat_ready)
    monkeypatch.setattr(health, "_scheduler_heartbeat_exists", probe)
    assert health.main() == (0 if heartbeat_ready else 1)
    expected_key = (
        health.EMAIL_SCHEDULER_HEARTBEAT_KEY
        if email_enabled
        else health.PLATFORM_SCHEDULER_HEARTBEAT_KEY
    )
    probe.assert_called_once_with(settings, heartbeat_key=expected_key)


def test_lightweight_platform_heartbeat_key_matches_runtime_contract():
    from app.infrastructure.runtime_readiness import PLATFORM_SCHEDULER_HEARTBEAT_KEY

    assert health.PLATFORM_SCHEDULER_HEARTBEAT_KEY == PLATFORM_SCHEDULER_HEARTBEAT_KEY
