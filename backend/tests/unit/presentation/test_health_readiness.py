from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import SecretStr

from app.core.config.settings import Settings
from app.domain.entities.entities import UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.presentation.api.v1.routes.health import (
    diagnostics,
    readiness,
    router,
)

_STRONG_APP_SECRET = "9Wv!mR3#kP7@xN2$zQ8&bL5^tY4*cH6+"


class _HealthyDatabase:
    async def execute(self, _statement: object) -> None:
        return None


class _FailingDatabase:
    async def execute(self, _statement: object) -> None:
        raise RuntimeError(
            "could not connect to postgresql://user:password@private-host/db"
        )


class HealthReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_detailed_operational_endpoints_require_super_admin(
        self,
    ) -> None:
        routes = {
            route.path: route
            for route in router.routes
            if hasattr(route, "dependant")
        }
        for path in ("/diagnostics", "/metrics"):
            dependency = routes[path].dependant.dependencies[0].call
            self.assertIsNotNone(dependency)
            allowed = await dependency(
                user=SimpleNamespace(role=UserRole.SUPER_ADMIN)
            )
            self.assertEqual(allowed.role, UserRole.SUPER_ADMIN)
            with self.assertRaises(AuthorizationError):
                await dependency(
                    user=SimpleNamespace(role=UserRole.AGENCY_STAFF)
                )

    async def test_missing_production_gemini_key_makes_readiness_503(
        self,
    ) -> None:
        settings = Settings(
            app_secret_key=_STRONG_APP_SECRET,
            app_env="production",
            processing_backend="background",
            google_api_key=None,
            gemini_project_alias="gct-prod-tier1",
            gemini_priority_capacity_calibrated=True,
        )
        with patch(
            "app.presentation.api.v1.routes.health."
            "get_ai_priority_coordinator"
        ) as coordinator:
            coordinator.return_value.snapshot.return_value = object()
            response = await readiness(
                db=_HealthyDatabase(),  # type: ignore[arg-type]
                settings=settings,
            )
        self.assertEqual(response.status_code, 503)
        self.assertIn(b'"gemini_api_credentials":"api_key_required"', response.body)

    async def test_complete_background_configuration_is_ready(self) -> None:
        settings = Settings(
            app_secret_key=_STRONG_APP_SECRET,
            app_env="production",
            processing_backend="background",
            google_api_key=SecretStr("configured-key"),
            gemini_project_alias="gct-prod-tier1",
            gemini_priority_capacity_calibrated=True,
        )
        with patch(
            "app.presentation.api.v1.routes.health."
            "get_ai_priority_coordinator"
        ) as coordinator:
            coordinator.return_value.snapshot.return_value = object()
            response = await readiness(
                db=_HealthyDatabase(),  # type: ignore[arg-type]
                settings=settings,
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'"gemini_api_credentials":"configured_or_non_production"', response.body)
        self.assertIn(b'"mobile_realtime":', response.body)
        self.assertIn(b'"mobile_offline_authorization":"disabled"', response.body)
        self.assertIn(b'"revision":"unknown"', response.body)

    async def test_background_scheduler_failure_makes_readiness_503(
        self,
    ) -> None:
        settings = Settings(
            app_secret_key=_STRONG_APP_SECRET,
            app_env="development",
            processing_backend="background",
        )
        with patch(
            "app.presentation.api.v1.routes.health."
            "get_ai_priority_coordinator"
        ) as coordinator:
            coordinator.return_value.snapshot.side_effect = ConnectionError(
                "redis unavailable"
            )
            response = await readiness(
                db=_HealthyDatabase(),  # type: ignore[arg-type]
                settings=settings,
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn(b'"ai_priority_redis":"unreachable"', response.body)

    async def test_missing_required_worker_queue_makes_readiness_503(
        self,
    ) -> None:
        settings = Settings(
            app_secret_key=_STRONG_APP_SECRET,
            app_env="production",
            processing_backend="celery",
        )
        with (
            patch(
                "app.presentation.api.v1.routes.health."
                "get_ai_priority_coordinator"
            ) as coordinator,
            patch(
                "app.presentation.api.v1.routes.health."
                "gemini_configuration_readiness",
                return_value=(
                    {
                        "gemini_api_credentials": "configured_or_non_production",
                    },
                    True,
                ),
            ),
            patch(
                "app.presentation.api.v1.routes.health."
                "gemini_worker_readiness",
                return_value=(
                    {
                        "gemini_extraction_worker": "available",
                        "gemini_verification_worker": "queue_not_consumed",
                    },
                    False,
                ),
            ),
        ):
            coordinator.return_value.snapshot.return_value = object()
            response = await readiness(
                db=_HealthyDatabase(),  # type: ignore[arg-type]
                settings=settings,
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn(b'"status":"degraded"', response.body)
        self.assertIn(b'"queue_not_consumed"', response.body)

    async def test_readiness_does_not_log_raw_database_exception(self) -> None:
        settings = Settings(
            app_secret_key=_STRONG_APP_SECRET,
            app_env="development",
            processing_backend="background",
        )
        with (
            patch(
                "app.presentation.api.v1.routes.health.logger.error"
            ) as log_error,
            patch(
                "app.presentation.api.v1.routes.health."
                "get_ai_priority_coordinator"
            ) as coordinator,
        ):
            coordinator.return_value.snapshot.return_value = object()
            response = await readiness(
                db=_FailingDatabase(),  # type: ignore[arg-type]
                settings=settings,
            )

        self.assertEqual(response.status_code, 503)
        log_error.assert_called_once_with(
            "health_check_db_failed",
            error_type="RuntimeError",
        )
        self.assertNotIn(b"password", response.body)

    async def test_diagnostics_does_not_log_raw_database_exception(
        self,
    ) -> None:
        settings = Settings(
            app_secret_key=_STRONG_APP_SECRET,
            app_env="development",
        )
        with patch(
            "app.presentation.api.v1.routes.health.logger.error"
        ) as log_error:
            response = await diagnostics(
                db=_FailingDatabase(),  # type: ignore[arg-type]
                settings=settings,
            )

        self.assertEqual(response.status_code, 503)
        log_error.assert_called_once_with(
            "diagnostics_db_failed",
            error_type="RuntimeError",
        )
        self.assertNotIn(b"password", response.body)


if __name__ == "__main__":
    unittest.main()
