"""Dashboard, media and public-upload request budgets."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class RequestSettingsFields(BaseSettings):
    """Flat environment fields composed into the public Settings model."""

    # Anonymous/non-dashboard API fallback. Authenticated dashboard traffic is
    # keyed by the verified JWT subject below so staff behind one office NAT do
    # not consume a shared bucket.
    rate_limit_per_minute: int = Field(default=60, ge=0, le=100_000)
    dashboard_rate_limit_per_minute: int = Field(
        default=5_000,
        ge=0,
        le=100_000,
    )

    # A short token bucket sits in front of the minute allowance so one noisy
    # account cannot monopolize the shared dashboard edge lane. The capacity
    # admits normal page-load bursts while the refill rate bounds sustained
    # pressure from one verified account.
    dashboard_rate_limit_per_second: int = Field(default=50, ge=0, le=10_000)
    dashboard_rate_limit_burst: int = Field(default=150, ge=0, le=100_000)

    # Protected image streams use an independent budget. A DOCS view can load
    # many authorized images without consuming the staff member's dashboard
    # action allowance, while still retaining a bounded abuse guard.
    dashboard_media_rate_limit_per_minute: int = Field(
        default=50_000,
        ge=0,
        le=100_000,
    )
    dashboard_media_rate_limit_per_second: int = Field(default=50, ge=0, le=10_000)
    dashboard_media_rate_limit_burst: int = Field(default=100, ge=0, le=100_000)

    # Per Gunicorn worker. The cache contains only metadata-stripped dashboard
    # thumbnails and never changes the original files or database rows.
    dashboard_thumbnail_max_dimension: int = Field(default=320, ge=128, le=1_024)
    dashboard_thumbnail_cache_max_bytes: int = Field(
        default=16 * 1024 * 1024,
        ge=1024 * 1024,
        le=512 * 1024 * 1024,
    )

    # Credential lockouts must remain global across every API worker in
    # production.  Development and isolated tests can opt into the bounded
    # in-process fallback explicitly, but a Redis outage must never silently
    # weaken the production authentication boundary.
    login_lockout_require_redis: bool = True
    dashboard_rate_limit_require_redis: bool = True
    public_upload_bootstrap_session_rate_limit_per_minute: int = Field(
        default=30,
        ge=1,
        le=10_000,
    )
    public_upload_bootstrap_aggregate_rate_limit_per_minute: int = Field(
        default=600,
        ge=100,
        le=100_000,
    )
    public_upload_session_rate_limit_per_minute: int = Field(default=6, ge=1, le=1_000)
    public_upload_prepare_session_rate_limit_per_minute: int = Field(
        default=30,
        ge=1,
        le=1_000,
    )
    public_upload_prepare_aggregate_rate_limit_per_minute: int = Field(
        default=600,
        ge=100,
        le=100_000,
    )
    public_upload_aggregate_rate_limit_per_minute: int = Field(
        default=180,
        ge=100,
        le=100_000,
    )
    public_upload_followup_session_rate_limit_per_minute: int = Field(
        default=120,
        ge=1,
        le=10_000,
    )
    public_upload_followup_aggregate_rate_limit_per_minute: int = Field(
        default=6_000,
        ge=100,
        le=100_000,
    )
    public_upload_rate_limit_require_redis: bool = True
    public_upload_otp_phone_limit_per_hour: int = Field(default=30, ge=20, le=100)
    public_upload_otp_ip_limit_per_hour: int = Field(default=60, ge=20, le=500)
