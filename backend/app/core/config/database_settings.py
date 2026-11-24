"""PostgreSQL connection pools and deadlines."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class DatabaseSettings(BaseSettings):
    """PostgreSQL connection settings."""

    model_config = SettingsConfigDict(env_prefix="POSTGRES_", env_file=".env", extra="ignore")

    host: str = "localhost"
    port: int = 5432
    db: str = "passdetection"
    user: str = "passdetection_user"
    password: str = Field(..., repr=False, description="Must be set via POSTGRES_PASSWORD env var")
    # One process owns one SQLAlchemy pool. API and background-worker profiles
    # are intentionally separate so Celery prefork concurrency cannot multiply
    # an API-sized pool across every child process.
    pool_profile: Literal["api", "worker"] = "api"
    api_pool_size: int = Field(default=8, ge=1, le=64)
    api_max_overflow: int = Field(default=2, ge=0, le=64)
    worker_pool_size: int = Field(default=1, ge=1, le=8)
    worker_max_overflow: int = Field(default=0, ge=0, le=8)
    pool_timeout_seconds: float = Field(default=5.0, ge=0.5, le=60.0)
    pool_recycle_seconds: int = Field(default=1_800, ge=60, le=86_400)
    api_statement_timeout_ms: int = Field(default=15_000, ge=1_000, le=60_000)
    worker_statement_timeout_ms: int = Field(default=300_000, ge=1_000, le=900_000)
    lock_timeout_ms: int = Field(default=5_000, ge=100, le=30_000)
    idle_in_transaction_session_timeout_ms: int = Field(
        default=30_000,
        ge=1_000,
        le=120_000,
    )
    server_max_connections: int = Field(default=100, ge=20, le=10_000)
    reserved_connections: int = Field(default=10, ge=5, le=1_000)
    api_connection_budget: int = Field(default=80, ge=5, le=10_000)

    @model_validator(mode="after")
    def validate_connection_reserve(self) -> Self:
        if self.reserved_connections >= self.server_max_connections:
            raise ValueError(
                "POSTGRES_RESERVED_CONNECTIONS must be lower than POSTGRES_SERVER_MAX_CONNECTIONS"
            )
        usable = self.server_max_connections - self.reserved_connections
        if self.api_connection_budget > usable:
            raise ValueError(
                "POSTGRES_API_CONNECTION_BUDGET cannot exceed the server capacity "
                "remaining after POSTGRES_RESERVED_CONNECTIONS"
            )
        if self.pool_profile == "api" and self.lock_timeout_ms > self.api_statement_timeout_ms:
            raise ValueError(
                "POSTGRES_LOCK_TIMEOUT_MS cannot exceed POSTGRES_API_STATEMENT_TIMEOUT_MS"
            )
        if (
            self.pool_profile == "worker"
            and self.lock_timeout_ms > self.worker_statement_timeout_ms
        ):
            raise ValueError(
                "POSTGRES_LOCK_TIMEOUT_MS cannot exceed POSTGRES_WORKER_STATEMENT_TIMEOUT_MS"
            )
        return self

    @property
    def pool_size(self) -> int:
        return self.api_pool_size if self.pool_profile == "api" else self.worker_pool_size

    @property
    def max_overflow(self) -> int:
        return self.api_max_overflow if self.pool_profile == "api" else self.worker_max_overflow

    @property
    def maximum_process_connections(self) -> int:
        return self.pool_size + self.max_overflow

    @property
    def statement_timeout_ms(self) -> int:
        return (
            self.api_statement_timeout_ms
            if self.pool_profile == "api"
            else self.worker_statement_timeout_ms
        )

    @computed_field(repr=False)  # type: ignore[prop-decorator]  # Pydantic computed property
    @property
    def async_url(self) -> str:
        """Async DSN used by SQLAlchemy + asyncpg at runtime."""
        return self._connection_url("postgresql+asyncpg")

    @computed_field(repr=False)  # type: ignore[prop-decorator]  # Pydantic computed property
    @property
    def sync_url(self) -> str:
        """Sync DSN used by Alembic migrations."""
        return self._connection_url("postgresql+psycopg2")

    def _connection_url(self, driver: str) -> str:
        # Construct components before rendering: generated secrets may contain
        # delimiters such as @, /, %, or Unicode. Never log this rendered URL.
        return URL.create(
            driver,
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.db,
        ).render_as_string(hide_password=False)
