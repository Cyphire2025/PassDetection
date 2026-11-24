from __future__ import annotations

import pytest

from app.core.config.settings import DatabaseSettings, S3Settings, Settings


def test_database_repr_omits_password_and_both_rendered_connection_urls() -> None:
    settings = DatabaseSettings(password="synthetic-database-credential", _env_file=None)

    assert "synthetic-database-credential" not in repr(settings)
    assert "postgresql+asyncpg" not in repr(settings)
    assert "postgresql+psycopg2" not in repr(settings)
    assert "synthetic-database-credential" in settings.async_url
    assert "synthetic-database-credential" in settings.sync_url
    assert settings.model_dump()["password"] == "synthetic-database-credential"


def test_storage_repr_omits_both_credentials_without_changing_client_values() -> None:
    settings = S3Settings(
        access_key_id="synthetic-storage-access-key",
        secret_access_key="synthetic-storage-secret-key",
        _env_file=None,
    )

    assert "synthetic-storage-access-key" not in repr(settings)
    assert "synthetic-storage-secret-key" not in repr(settings)
    assert settings.access_key_id == "synthetic-storage-access-key"
    assert settings.secret_access_key == "synthetic-storage-secret-key"


@pytest.mark.parametrize(
    "field_name",
    ["app_secret_key", "whatsapp_access_token", "whatsapp_webhook_verify_token", "whatsapp_app_secret"],
)
def test_root_repr_omits_plaintext_signing_and_provider_secrets(field_name: str) -> None:
    values = {"app_secret_key": "synthetic-app-secret", field_name: "synthetic-sensitive-value"}
    settings = Settings(**values, _env_file=None)

    assert "synthetic-sensitive-value" not in repr(settings)
    assert getattr(settings, field_name) == "synthetic-sensitive-value"
