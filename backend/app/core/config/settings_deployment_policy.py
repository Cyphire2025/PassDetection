"""Cross-setting startup admission checks; called in the public model order."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from app.core.config.settings import Settings

_SettingsT = TypeVar("_SettingsT", bound="Settings")


def validate_database_connection_budget(settings: _SettingsT) -> _SettingsT:
    """Fail staging/production before process pools can exceed PostgreSQL."""

    if settings.app_env == "development":
        return settings
    database = settings.database
    api_per_process = database.api_pool_size + database.api_max_overflow
    api_claim = settings.web_concurrency * api_per_process
    if api_claim > database.api_connection_budget:
        raise ValueError(
            "WEB_CONCURRENCY multiplied by the API PostgreSQL pool exceeds "
            "POSTGRES_API_CONNECTION_BUDGET"
        )
    background_processes = (
        settings.worker_concurrency
        + settings.email_worker_concurrency
        + settings.email_ai_worker_concurrency
        + settings.my_photos_worker_concurrency
        + settings.gemini_extraction_max_concurrency
        + settings.gemini_verification_max_concurrency
        + settings.gemini_image_edit_max_concurrency
        + 1  # ECR batch worker; its asynchronous lanes share one pool.
        + 1  # Celery Beat scheduler process.
    )
    worker_per_process = database.worker_pool_size + database.worker_max_overflow
    total_claim = api_claim + (background_processes * worker_per_process)
    usable = database.server_max_connections - database.reserved_connections
    if total_claim > usable:
        raise ValueError(
            "Configured API and background process pools can claim "
            f"{total_claim} PostgreSQL connections, exceeding the usable "
            f"deployment budget of {usable}"
        )
    return settings


def validate_metrics_export_configuration(settings: _SettingsT) -> _SettingsT:
    host = settings.metrics_statsd_host.strip()
    if host != settings.metrics_statsd_host or any(character.isspace() for character in host):
        raise ValueError(
            "METRICS_STATSD_HOST must not contain surrounding or embedded whitespace"
        )
    if settings.metrics_export_required and settings.metrics_exporter != "statsd":
        raise ValueError(
            "METRICS_EXPORTER=statsd is required when METRICS_EXPORT_REQUIRED=true"
        )
    return settings


def validate_email_ai_lease_duration(settings: _SettingsT) -> _SettingsT:
    minimum_lease = (2 * settings.email_ai_analysis_timeout_seconds) + 30
    if settings.email_ai_lease_seconds < minimum_lease:
        raise ValueError(
            "EMAIL_AI_LEASE_SECONDS must cover two bounded analysis "
            "attempts plus a 30-second safety margin"
        )
    return settings


def validate_mcp_deployment(settings: _SettingsT) -> _SettingsT:
    if settings.mcp.enabled and settings.app_env != "development":
        if "enabled_capabilities" not in settings.mcp.model_fields_set:
            raise ValueError("Enabled MCP requires explicit rollout capabilities in staging/production")
        if any(urlsplit(origin).scheme != "https" for origin in (
            settings.mcp.public_origin, settings.mcp.frontend_origin,
        )):
            raise ValueError("Enabled MCP in staging/production requires HTTPS origins")
        if settings.mcp.frontend_origin not in settings.allowed_origins:
            raise ValueError("MCP frontend origin must be an approved dashboard origin")
    return settings
