"""Container healthcheck for the singleton email Beat scheduler."""

from __future__ import annotations

from app.core.config.settings import get_settings
from app.infrastructure.email.readiness import (
    EMAIL_SCHEDULER_HEARTBEAT_KEY,
    _scheduler_heartbeat_exists,
)

# Keep this probe lightweight: importing the complete platform readiness stack
# alongside Beat would consume the scheduler container's small memory budget.
PLATFORM_SCHEDULER_HEARTBEAT_KEY = "passdetection:platform:scheduler-heartbeat:v1"


def main() -> int:
    settings = get_settings()
    heartbeat_key = (
        EMAIL_SCHEDULER_HEARTBEAT_KEY
        if settings.email_integrations_enabled
        else PLATFORM_SCHEDULER_HEARTBEAT_KEY
    )
    return 0 if _scheduler_heartbeat_exists(settings, heartbeat_key=heartbeat_key) else 1


if __name__ == "__main__":
    raise SystemExit(main())
