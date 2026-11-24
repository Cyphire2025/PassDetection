"""Public flat application configuration and ordered startup validation."""

from __future__ import annotations

from functools import lru_cache
from typing import Callable, Self, TypeVar, cast
from urllib.parse import urlsplit

from pydantic import computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config.ai_settings_fields import AISettingsFields
from app.core.config.database_settings import DatabaseSettings as DatabaseSettings
from app.core.config.email_settings_fields import EmailSettingsFields
from app.core.config.identity_settings_fields import IdentitySettingsFields
from app.core.config.ingestion_settings_fields import IngestionSettingsFields
from app.core.config.jwt_settings import JWTSettings as JWTSettings
from app.core.config.mobile_settings import MobileSettings as MobileSettings
from app.core.config.my_photos_settings import MyPhotosSettings as MyPhotosSettings
from app.core.config.redis_settings import RedisSettings as RedisSettings
from app.core.config.request_settings_fields import RequestSettingsFields
from app.core.config.runtime_settings_fields import RuntimeSettingsFields
from app.core.config.s3_settings import S3Settings as S3Settings
from app.core.config.settings_deployment_policy import (
    validate_database_connection_budget,
    validate_email_ai_lease_duration,
    validate_mcp_deployment,
    validate_metrics_export_configuration,
)
from app.core.config.settings_identity_policy import (
    validate_dashboard_signing_secret,
    validate_identity_security_configuration,
)
from app.core.config.settings_mobile_policy import (
    validate_mobile_app_integrity_configuration,
    validate_mobile_offline_lease_signing_keys,
    validate_mobile_otp_configuration,
    validate_mobile_production_signing_secret,
    validate_mobile_verified_link_configuration,
)
from app.core.config.whatsapp_settings_fields import WhatsAppSettingsFields

_SettingsValue = TypeVar("_SettingsValue", bound=BaseSettings)


def _load_environment_settings(settings_type: type[_SettingsValue]) -> _SettingsValue:
    """Keep pydantic-settings environment construction visible to strict typing."""

    factory = cast(Callable[[], _SettingsValue], settings_type)
    return factory()


class Settings(
    WhatsAppSettingsFields,
    IdentitySettingsFields,
    EmailSettingsFields,
    AISettingsFields,
    IngestionSettingsFields,
    RequestSettingsFields,
    RuntimeSettingsFields,
):
    """
    Root application settings.

    All child settings objects are composed here so the entire
    application has a single, consistent configuration surface.
    """

    # Pydantic collects base fields in reverse MRO: these bases retain the
    # published field order while each domain owns its declarations once.

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("email_oauth_frontend_return_url", "password_recovery_frontend_url")
    @classmethod
    def validate_frontend_return_url(cls, value: str) -> str:
        normalized = value.strip()
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError(
                "Frontend return URLs must be absolute HTTP(S) URLs "
                "without embedded credentials or a fragment"
            )
        return normalized

    @model_validator(mode="after")
    def validate_mobile_otp_configuration(self) -> Self:
        return validate_mobile_otp_configuration(self)

    @model_validator(mode="after")
    def validate_identity_security_configuration(self) -> Self:
        """Reject ambiguous key rings and unsafe recovery-development controls."""
        return validate_identity_security_configuration(self)

    @model_validator(mode="after")
    def validate_database_connection_budget(self) -> Self:
        """Fail staging/production before process pools can exceed PostgreSQL."""
        return validate_database_connection_budget(self)

    @model_validator(mode="after")
    def validate_metrics_export_configuration(self) -> Self:
        return validate_metrics_export_configuration(self)

    @model_validator(mode="after")
    def validate_dashboard_signing_secret(self) -> Self:
        """Reject weak shared signing keys outside local development."""
        return validate_dashboard_signing_secret(self)

    @model_validator(mode="after")
    def validate_mobile_production_signing_secret(self) -> Self:
        """Fail startup before a weak production mobile signing key can be used."""
        return validate_mobile_production_signing_secret(self)

    @model_validator(mode="after")
    def validate_mobile_offline_lease_signing_keys(self) -> Self:
        """Fail closed outside development when mobile offline auth cannot be verified."""
        return validate_mobile_offline_lease_signing_keys(self)

    @model_validator(mode="after")
    def validate_my_photos_provider_configuration(self) -> Self:
        """Never permit deterministic biometric/media simulation outside local development."""

        self.my_photos.validate_runtime_environment(self.app_env)
        return self

    @model_validator(mode="after")
    def validate_mobile_verified_link_configuration(self) -> Self:
        """Keep the production Android association document available and exact."""
        return validate_mobile_verified_link_configuration(self)

    @model_validator(mode="after")
    def validate_mobile_app_integrity_configuration(self) -> Self:
        """Reject an enforcement rollout that lacks cross-worker/provider bindings."""
        return validate_mobile_app_integrity_configuration(self)

    @model_validator(mode="after")
    def validate_email_ai_lease_duration(self) -> Self:
        return validate_email_ai_lease_duration(self)

    @model_validator(mode="after")
    def validate_mcp_deployment(self) -> Self:
        return validate_mcp_deployment(self)

    @property
    def email_ai_runtime_ready(self) -> bool:
        """Whether workers may send mailbox content to the configured AI."""

        api_key = (
            self.google_api_key.get_secret_value().strip()
            if self.google_api_key is not None
            else ""
        )
        return bool(
            self.email_integrations_enabled
            and self.email_sync_enabled
            and self.email_ai_enabled
            and api_key
        )

    @property
    def email_ai_notifications_ready(self) -> bool:
        return bool(self.email_ai_runtime_ready and self.email_ai_notifications_enabled)

    @computed_field(repr=False)  # type: ignore[prop-decorator]  # Pydantic property
    @property
    def database(self) -> DatabaseSettings:
        return _load_environment_settings(DatabaseSettings)

    @computed_field(repr=False)  # type: ignore[prop-decorator]  # Pydantic property
    @property
    def redis(self) -> RedisSettings:
        return _load_environment_settings(RedisSettings)

    @computed_field(repr=False)  # type: ignore[prop-decorator]  # Pydantic property
    @property
    def jwt(self) -> JWTSettings:
        return _load_environment_settings(JWTSettings)

    @computed_field(repr=False)  # type: ignore[prop-decorator]  # Pydantic property
    @property
    def mobile(self) -> MobileSettings:
        return _load_environment_settings(MobileSettings)

    @computed_field(repr=False)  # type: ignore[prop-decorator]  # Pydantic property
    @property
    def my_photos(self) -> MyPhotosSettings:
        return _load_environment_settings(MyPhotosSettings)

    @computed_field(repr=False)  # type: ignore[prop-decorator]  # Pydantic property
    @property
    def s3(self) -> S3Settings:
        return _load_environment_settings(S3Settings)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance."""
    return _load_environment_settings(Settings)
