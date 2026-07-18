from __future__ import annotations

import unittest

from pydantic import SecretStr

from app.core.config.settings import Settings
from app.infrastructure.ai_priority.identity import (
    gemini_configuration_readiness,
    gemini_runtime_identity,
)


class AiPriorityIdentityTests(unittest.TestCase):
    def test_identity_is_safe_and_never_contains_key_or_query(self) -> None:
        settings = Settings(
            app_secret_key="unit-test-secret",
            google_api_key=SecretStr("super-secret-google-key"),
            gemini_project_alias="gct-prod-tier1",
            gemini_config_version="2026-07-18.1",
            gemini_api_base_url=(
                "https://user:password@generativelanguage.googleapis.com/"
                "v1beta?key=must-not-log#fragment"
            ),
        )
        identity = gemini_runtime_identity(settings)
        payload = identity.to_safe_dict()
        serialized = repr(payload)
        self.assertTrue(identity.project_alias_configured)
        self.assertTrue(payload["api_key_configured"])
        self.assertEqual(
            payload["api_endpoint"],
            "https://generativelanguage.googleapis.com/v1beta",
        )
        self.assertNotIn("super-secret", serialized)
        self.assertNotIn("password", serialized)
        self.assertNotIn("?key=", serialized)

    def test_default_alias_is_explicitly_unconfigured(self) -> None:
        settings = Settings(app_secret_key="unit-test-secret")
        self.assertFalse(
            gemini_runtime_identity(settings).project_alias_configured
        )

    def test_blank_key_is_not_treated_as_configured(self) -> None:
        settings = Settings(
            app_secret_key="unit-test-secret",
            google_api_key=SecretStr("   "),
        )
        self.assertFalse(gemini_runtime_identity(settings).api_key_configured)

    def test_production_requires_credentials_alias_and_capacity(self) -> None:
        unready = Settings(
            app_secret_key="unit-test-secret",
            app_env="production",
            google_api_key=None,
        )
        checks, ready = gemini_configuration_readiness(unready)
        self.assertFalse(ready)
        self.assertEqual(
            checks,
            {
                "gemini_verification": "enabled",
                "gemini_api_credentials": "api_key_required",
                "gemini_priority_capacity": "calibration_required",
                "gemini_runtime_identity": "project_alias_required",
            },
        )

        calibrated = Settings(
            app_secret_key="unit-test-secret",
            app_env="production",
            gemini_priority_capacity_calibrated=True,
            gemini_project_alias="gct-prod-tier1",
            google_api_key=SecretStr("configured-key"),
        )
        checks, ready = gemini_configuration_readiness(calibrated)
        self.assertTrue(ready)
        self.assertEqual(
            checks["gemini_priority_capacity"],
            "calibrated_or_non_production",
        )
        self.assertEqual(
            checks["gemini_runtime_identity"],
            "configured_or_non_production",
        )
        self.assertEqual(
            checks["gemini_api_credentials"],
            "configured_or_non_production",
        )

    def test_disabled_verification_still_requires_extraction_gemini_gates(
        self,
    ) -> None:
        settings = Settings(
            app_secret_key="unit-test-secret",
            app_env="production",
            gemini_verification_enabled=False,
            google_api_key=None,
        )
        checks, ready = gemini_configuration_readiness(settings)
        self.assertFalse(ready)
        self.assertEqual(checks["gemini_verification"], "disabled")
        self.assertEqual(
            checks["gemini_api_credentials"],
            "api_key_required",
        )
        self.assertEqual(
            checks["gemini_priority_capacity"],
            "calibration_required",
        )
        self.assertEqual(
            checks["gemini_runtime_identity"],
            "project_alias_required",
        )


if __name__ == "__main__":
    unittest.main()
