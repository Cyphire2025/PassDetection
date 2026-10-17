"""Independent disclosure kill switch and explicit cryptographic configuration."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class TravellerReuseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRAVELLER_REUSE_", extra="ignore")

    disclosure_enabled: bool = False
    # Independent keys permit disabling or rotating history without changing login.
    lookup_key: SecretStr | None = None
    encryption_key: SecretStr | None = None
    key_version: str = "v1"
    request_network_limit_per_minute: int = Field(default=600, ge=1, le=100_000)
    request_session_limit_per_minute: int = Field(default=60, ge=1, le=10_000)


@lru_cache
def get_traveller_reuse_settings() -> TravellerReuseSettings:
    return TravellerReuseSettings()
