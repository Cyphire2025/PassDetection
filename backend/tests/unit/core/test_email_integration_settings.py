from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config.settings import Settings


def _settings(**overrides: object) -> Settings:
    return Settings(
        app_secret_key="unit-test-only",
        _env_file=None,
        **overrides,
    )


def test_email_capabilities_are_disabled_by_default() -> None:
    settings = _settings()

    assert settings.email_integrations_enabled is False
    assert settings.email_sync_enabled is False
    assert settings.email_attachment_processing_enabled is False
    assert settings.email_link_retrieval_enabled is False
    assert settings.email_auto_actions_enabled is False
    assert settings.email_token_encryption_key is None
    assert settings.email_token_decryption_keys == {}
    assert settings.gmail_oauth_client_secret is None


def test_email_secret_values_remain_redacted() -> None:
    settings = _settings(
        email_token_encryption_key="email-token-key-value",
        email_token_decryption_keys={"1": "prior-email-token-key-value"},
        gmail_oauth_client_secret="gmail-client-secret-value",
    )

    assert "email-token-key-value" not in str(settings.email_token_encryption_key)
    assert "prior-email-token-key-value" not in repr(settings)
    assert "gmail-client-secret-value" not in str(settings.gmail_oauth_client_secret)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("email_sync_interval_seconds", 59),
        ("email_sync_lease_seconds", 29),
        ("email_sync_full_lookback_days", 0),
        ("email_sync_max_messages", 0),
        ("email_attachment_max_bytes", 1024),
        ("email_pdf_max_pages", 0),
        ("email_storage_orphan_grace_hours", 0),
    ],
)
def test_email_processing_limits_are_bounded(
    field_name: str,
    invalid_value: int,
) -> None:
    with pytest.raises(ValidationError):
        _settings(**{field_name: invalid_value})


def test_oauth_redirect_destinations_must_be_explicit_http_urls() -> None:
    assert _settings().email_oauth_frontend_return_url == (
        "http://localhost:3000/email-integrations"
    )

    with pytest.raises(ValidationError):
        _settings(email_oauth_frontend_return_url="//attacker.example/email-integrations")
    with pytest.raises(ValidationError):
        _settings(gmail_oauth_redirect_uri="https://user:pass@example.com/callback")
