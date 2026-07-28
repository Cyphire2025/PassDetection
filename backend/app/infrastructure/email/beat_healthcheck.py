"""Container healthcheck for the singleton email Beat scheduler."""

from __future__ import annotations

from app.core.config.settings import get_settings
from app.infrastructure.email.readiness import _scheduler_heartbeat_exists


def main() -> int:
    return 0 if _scheduler_heartbeat_exists(get_settings()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
