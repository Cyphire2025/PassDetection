"""Regression tests for WhatsApp webhook verification helpers."""

from __future__ import annotations

import hashlib
import hmac
import types
import unittest
from unittest.mock import patch

from app.presentation.api.v1.routes.whatsapp import _verify_meta_signature


class WhatsAppWebhookSecurityTests(unittest.TestCase):
    def test_valid_meta_signature_is_accepted(self) -> None:
        body = b'{"object":"whatsapp_business_account","entry":[]}'
        secret = "test-app-secret"
        signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

        with patch(
            "app.presentation.api.v1.routes.whatsapp.get_settings",
            return_value=types.SimpleNamespace(whatsapp_app_secret=secret),
        ):
            self.assertTrue(_verify_meta_signature(body, f"sha256={signature}"))

    def test_invalid_meta_signature_is_rejected_when_secret_is_configured(self) -> None:
        with patch(
            "app.presentation.api.v1.routes.whatsapp.get_settings",
            return_value=types.SimpleNamespace(whatsapp_app_secret="test-app-secret"),
        ):
            self.assertFalse(_verify_meta_signature(b"{}", "sha256=bad"))
            self.assertFalse(_verify_meta_signature(b"{}", None))

    def test_missing_app_secret_rejects_unsigned_production_webhooks(self) -> None:
        with patch(
            "app.presentation.api.v1.routes.whatsapp.get_settings",
            return_value=types.SimpleNamespace(whatsapp_app_secret="", app_env="production"),
        ):
            self.assertFalse(_verify_meta_signature(b"{}", None))

    def test_missing_app_secret_rejects_unsigned_staging_webhooks(self) -> None:
        with patch(
            "app.presentation.api.v1.routes.whatsapp.get_settings",
            return_value=types.SimpleNamespace(whatsapp_app_secret="", app_env="staging"),
        ):
            self.assertFalse(_verify_meta_signature(b"{}", None))

    def test_missing_app_secret_allows_local_development_webhooks(self) -> None:
        with patch(
            "app.presentation.api.v1.routes.whatsapp.get_settings",
            return_value=types.SimpleNamespace(whatsapp_app_secret="", app_env="development"),
        ):
            self.assertTrue(_verify_meta_signature(b"{}", None))


if __name__ == "__main__":
    unittest.main()
