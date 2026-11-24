from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config.settings import Settings


@pytest.mark.parametrize(
    ("host", "sender"),
    [(None, None), ("smtp.example.test", None), (None, "dashboard@example.test")],
)
def test_recovery_smtp_requires_complete_delivery_configuration(
    test_settings: Settings,
    host: str | None,
    sender: str | None,
) -> None:
    with pytest.raises(ValidationError, match="PASSWORD_RECOVERY_DELIVERY_PROVIDER=smtp requires"):
        Settings(
            app_secret_key=test_settings.app_secret_key,
            password_recovery_delivery_provider="smtp",
            password_recovery_smtp_host=host,
            password_recovery_smtp_sender=sender,
            _env_file=None,
        )


def test_valid_smtp_configuration_preserves_credentials_and_redacts_repr(
    test_settings: Settings,
) -> None:
    settings = Settings(
        app_secret_key=test_settings.app_secret_key,
        password_recovery_delivery_provider="smtp",
        password_recovery_smtp_host="smtp.example.test",
        password_recovery_smtp_sender="dashboard@example.test",
        password_recovery_smtp_password="synthetic-smtp-secret",
        _env_file=None,
    )
    assert settings.password_recovery_delivery_provider == "smtp"
    assert settings.password_recovery_smtp_host == "smtp.example.test"
    assert settings.password_recovery_smtp_password is not None
    assert settings.password_recovery_smtp_password.get_secret_value() == "synthetic-smtp-secret"
    assert "synthetic-smtp-secret" not in repr(settings)


def test_flat_environment_values_still_override_dotenv_across_settings_domains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    test_settings: Settings,
) -> None:
    # This file contains synthetic configuration only; the checkout .env is not read.
    dotenv = tmp_path / "synthetic.env"
    dotenv.write_text(
        "APP_NAME=File name\n"
        "DASHBOARD_RATE_LIMIT_PER_MINUTE=1234\n"
        "GEMINI_MODEL=synthetic-model-from-file\n"
        "EMAIL_AI_MAX_CANDIDATES=12\n"
        "IDENTITY_PREVIOUS_KEY_LIMIT=2\n"
        "WHATSAPP_REMINDER_TEMPLATE_NAME=synthetic_file_template\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("APP_NAME", "Environment name")
    monkeypatch.setenv("DASHBOARD_RATE_LIMIT_PER_MINUTE", "2345")
    monkeypatch.setenv("GEMINI_MODEL", "synthetic-model-from-environment")
    monkeypatch.setenv("EMAIL_AI_MAX_CANDIDATES", "13")
    monkeypatch.setenv("IDENTITY_PREVIOUS_KEY_LIMIT", "1")
    monkeypatch.setenv("WHATSAPP_REMINDER_TEMPLATE_NAME", "synthetic_environment_template")
    settings = Settings(app_secret_key=test_settings.app_secret_key, _env_file=dotenv)
    assert settings.app_name == "Environment name"
    assert settings.dashboard_rate_limit_per_minute == 2345
    assert settings.gemini_model == "synthetic-model-from-environment"
    assert settings.email_ai_max_candidates == 13
    assert settings.identity_previous_key_limit == 1
    assert settings.whatsapp_reminder_template_name == "synthetic_environment_template"


def test_explicit_flat_constructor_values_keep_precedence_over_environment(
    monkeypatch: pytest.MonkeyPatch,
    test_settings: Settings,
) -> None:
    monkeypatch.setenv("APP_NAME", "Environment name")
    monkeypatch.setenv("DASHBOARD_RATE_LIMIT_PER_MINUTE", "2345")
    settings = Settings(
        app_secret_key=test_settings.app_secret_key,
        app_name="Explicit name",
        dashboard_rate_limit_per_minute=3456,
        _env_file=None,
    )
    assert settings.app_name == "Explicit name"
    assert settings.dashboard_rate_limit_per_minute == 3456
