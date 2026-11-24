"""Redis endpoints and durability-domain isolation."""

from __future__ import annotations

from typing import Literal, Self
from urllib.parse import quote

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RedisSettings(BaseSettings):
    """Redis connections partitioned by durability and eviction semantics.

    The legacy endpoint remains the development fallback. Production Compose
    enables ``domain_isolation_required`` and supplies four independent
    endpoints so broker pressure cannot weaken login throttles, realtime fanout,
    or evictable OCR caches.
    """

    model_config = SettingsConfigDict(env_prefix="REDIS_", env_file=".env", extra="ignore")

    host: str = "localhost"
    port: int = 6379
    username: str | None = None
    password: SecretStr = Field(default=SecretStr(""), repr=False)
    db: int = Field(default=0, ge=0, le=15)
    domain_isolation_required: bool = False

    broker_host: str | None = None
    broker_port: int | None = Field(default=None, ge=1, le=65_535)
    broker_username: str | None = None
    broker_password: SecretStr | None = Field(default=None, repr=False)
    broker_db: int | None = Field(default=None, ge=0, le=15)

    security_host: str | None = None
    security_port: int | None = Field(default=None, ge=1, le=65_535)
    security_username: str | None = None
    security_password: SecretStr | None = Field(default=None, repr=False)
    security_db: int | None = Field(default=None, ge=0, le=15)

    realtime_host: str | None = None
    realtime_port: int | None = Field(default=None, ge=1, le=65_535)
    realtime_username: str | None = None
    realtime_password: SecretStr | None = Field(default=None, repr=False)
    realtime_db: int | None = Field(default=None, ge=0, le=15)

    cache_host: str | None = None
    cache_port: int | None = Field(default=None, ge=1, le=65_535)
    cache_username: str | None = None
    cache_password: SecretStr | None = Field(default=None, repr=False)
    cache_db: int | None = Field(default=None, ge=0, le=15)

    @staticmethod
    def _normalized_host(value: str, *, field_name: str) -> str:
        normalized = value.strip()
        if not normalized or any(character.isspace() for character in normalized):
            raise ValueError(f"{field_name} must be a non-empty host without whitespace")
        return normalized

    @field_validator(
        "host",
        "broker_host",
        "security_host",
        "realtime_host",
        "cache_host",
        mode="before",
    )
    @classmethod
    def validate_redis_host(cls, value: object, info: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Redis hosts must be strings")
        field_name = getattr(info, "field_name", "Redis host")
        return cls._normalized_host(value, field_name=str(field_name).upper())

    @staticmethod
    def _secret_value(value: SecretStr | None, fallback: SecretStr) -> str:
        selected = value if value is not None else fallback
        return selected.get_secret_value()

    @staticmethod
    def _connection_url(
        *,
        host: str,
        port: int,
        username: str | None,
        password: str,
        db: int,
    ) -> str:
        encoded_password = quote(password, safe="")
        if username:
            encoded_username = quote(username.strip(), safe="")
            credentials = encoded_username
            if password:
                credentials += f":{encoded_password}"
            authority = f"{credentials}@"
        elif password:
            authority = f":{encoded_password}@"
        else:
            authority = ""
        return f"redis://{authority}{host}:{port}/{db}"

    def _domain_endpoint(
        self,
        domain: Literal["broker", "security", "realtime", "cache"],
    ) -> tuple[str, int, str | None, str, int]:
        host = getattr(self, f"{domain}_host") or self.host
        port = getattr(self, f"{domain}_port") or self.port
        username = getattr(self, f"{domain}_username")
        if username is None:
            username = self.username
        password = self._secret_value(getattr(self, f"{domain}_password"), self.password)
        database = getattr(self, f"{domain}_db")
        if database is None:
            database = self.db
        return host, port, username, password, database

    def _domain_url(self, domain: Literal["broker", "security", "realtime", "cache"]) -> str:
        host, port, username, password, database = self._domain_endpoint(domain)
        return self._connection_url(
            host=host,
            port=port,
            username=username,
            password=password,
            db=database,
        )

    @model_validator(mode="after")
    def validate_domain_isolation(self) -> Self:
        if not self.domain_isolation_required:
            return self
        domains: tuple[Literal["broker", "security", "realtime", "cache"], ...] = (
            "broker",
            "security",
            "realtime",
            "cache",
        )
        missing_hosts = [domain for domain in domains if getattr(self, f"{domain}_host") is None]
        if missing_hosts:
            raise ValueError(
                "REDIS_DOMAIN_ISOLATION_REQUIRED needs explicit hosts for: "
                + ", ".join(missing_hosts)
            )
        endpoints: dict[tuple[str, int, int], str] = {}
        for domain in domains:
            host, port, _username, password, database = self._domain_endpoint(domain)
            if not password:
                raise ValueError(
                    f"REDIS_{domain.upper()}_PASSWORD is required when domain isolation is enabled"
                )
            endpoint = (host.casefold(), port, database)
            previous = endpoints.setdefault(endpoint, domain)
            if previous != domain:
                raise ValueError(
                    "Redis domain endpoints must be distinct; "
                    f"{previous} and {domain} resolve to the same host, port, and database"
                )
        return self

    @property
    def url(self) -> str:
        """Legacy compatibility endpoint; never serialized with model data."""

        return self._connection_url(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password.get_secret_value(),
            db=self.db,
        )

    @property
    def broker_url(self) -> str:
        return self._domain_url("broker")

    @property
    def security_url(self) -> str:
        return self._domain_url("security")

    @property
    def realtime_url(self) -> str:
        return self._domain_url("realtime")

    @property
    def cache_url(self) -> str:
        return self._domain_url("cache")
