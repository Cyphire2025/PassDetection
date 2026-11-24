"""Metrics, durable processing and untrusted document ingestion settings."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class IngestionSettingsFields(BaseSettings):
    """Flat environment fields composed into the public Settings model."""

    sentry_dsn: str | None = None

    # General HTTP/business metrics leave each API or Celery process through a
    # non-blocking StatsD boundary. Production Compose requires this exporter;
    # an external Prometheus-compatible collector owns aggregation and SLOs.
    metrics_exporter: Literal["disabled", "statsd"] = "disabled"
    metrics_export_required: bool = False
    metrics_statsd_host: str = Field(default="localhost", min_length=1, max_length=253)
    metrics_statsd_port: int = Field(default=9125, ge=1, le=65_535)
    metrics_namespace: str = Field(
        default="passdetection",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$",
    )
    processing_backend: Literal["background", "celery"] = "background"
    processing_job_max_attempts: int = Field(default=3, ge=1, le=10)
    processing_job_timeout_seconds: int = Field(default=45, ge=15, le=300)
    processing_watchdog_delay_seconds: float = Field(default=8.0, ge=3.0, le=30.0)
    processing_worker_ping_timeout_seconds: float = Field(default=1.0, ge=0.2, le=5.0)
    processing_worker_readiness_cache_seconds: float = Field(
        default=15.0,
        ge=1.0,
        le=300.0,
    )
    upload_max_file_size_bytes: int = Field(default=10 * 1024 * 1024, ge=1024 * 1024)
    upload_max_pixels: int = Field(default=24_000_000, ge=1_000_000)

    # All passport images, distribution PDFs, and public-upload documents are
    # untrusted until the original bytes have crossed the malware boundary.
    # This switch exists for deliberately document-free deployments; routes
    # fail closed when disabled rather than silently bypassing scanning.
    untrusted_document_ingestion_enabled: bool = True
    malware_scanner_enabled: bool = False
    malware_scanner_host: str = "localhost"
    malware_scanner_port: int = Field(default=3310, ge=1, le=65535)
    malware_scanner_timeout_seconds: float = Field(default=2.0, ge=0.2, le=10.0)
    malware_quarantine_enabled: bool = True
    malware_quarantine_prefix: str = Field(
        default="security-quarantine",
        min_length=3,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$",
    )
    malware_quarantine_retention_days: int = Field(default=14, ge=1, le=90)
    ocr_cache_ttl_seconds: int = Field(default=3600, ge=0)
