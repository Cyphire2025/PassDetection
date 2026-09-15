"""Mobile authentication, delivery and device policy configuration."""

from __future__ import annotations

import json
import re
from typing import Literal, Self
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MobileSettings(BaseSettings):
    """GC mobile authentication, OTP, and synchronization settings."""

    model_config = SettingsConfigDict(env_prefix="MOBILE_", env_file=".env", extra="ignore")

    enabled: bool = False
    jwt_secret_key: SecretStr | None = None
    jwt_issuer: str = Field(default="passdetection", min_length=3, max_length=120)
    jwt_audience: str = Field(default="gc-mobile", min_length=3, max_length=120)
    access_token_expire_minutes: int = Field(default=15, ge=5, le=60)
    refresh_token_expire_days: int = Field(default=30, ge=1, le=90)
    # Ed25519 is intentionally independent from the symmetric online access
    # token profile. Public verification keys are embedded in reviewed mobile
    # builds; the active PKCS8 private key remains backend-only.
    offline_lease_active_kid: str | None = Field(default=None, max_length=64)
    offline_lease_private_key_b64: SecretStr | None = None
    offline_lease_public_keys_json: str | None = Field(default=None, max_length=8_192)
    offline_lease_issuer: str = Field(
        default="passdetection-mobile-offline",
        min_length=3,
        max_length=120,
    )
    offline_lease_audience: str = Field(
        default="gc-mobile-offline",
        min_length=3,
        max_length=120,
    )
    offline_lease_ttl_minutes: int = Field(default=720, ge=5, le=1_440)
    otp_provider: Literal["disabled", "development", "whatsapp"] = "disabled"
    otp_development_code: SecretStr | None = None
    otp_ttl_seconds: int = Field(default=300, ge=60, le=900)
    otp_delivery_timeout_seconds: float = Field(default=10.0, ge=1.0, le=30.0)
    otp_resend_cooldown_seconds: int = Field(default=60, ge=15, le=600)
    otp_max_attempts: int = Field(default=5, ge=1, le=10)
    otp_phone_limit_per_hour: int = Field(default=10, ge=1, le=100)
    otp_ip_limit_per_hour: int = Field(default=30, ge=1, le=1_000)
    otp_require_redis: bool = True
    # Server-only Photon endpoint; replace with a private instance without an APK update.
    journey_geocoding_url: str | None = Field(
        default="https://photon.komoot.io/api/", max_length=2_048
    )
    journey_geocoding_user_agent: str = Field(
        default="GlobalConnects-TripJourney/1.0", min_length=8, max_length=255
    )
    journey_geocoding_timeout_seconds: float = Field(default=5.0, ge=1, le=10)
    journey_geocoding_cache_ttl_seconds: int = Field(default=2_592_000, ge=86_400, le=7_776_000)
    journey_geocoding_failure_ttl_seconds: int = Field(default=300, ge=30, le=3_600)

    @field_validator("journey_geocoding_url")
    @classmethod
    def validate_journey_geocoding_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or any(character.isspace() for character in value)
        ):
            raise ValueError("Journey geocoding URL must be HTTPS without credentials or query")
        return value

    @field_validator("journey_geocoding_user_agent")
    @classmethod
    def validate_journey_geocoding_user_agent(cls, value: str) -> str:
        if (
            len(value.strip()) < 8
            or not value.isascii()
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise ValueError("Journey geocoding User-Agent must be printable ASCII")
        return value.strip()

    sync_page_size: int = Field(default=200, ge=25, le=500)
    # Shared dashboard/API/mobile capacity contracts. These are deliberately
    # configurable, but one deployed environment must expose and enforce the
    # same values instead of allowing clients to discover a hard ceiling late.
    sync_max_incremental_changes: int = Field(default=10_000, ge=500, le=100_000)
    max_group_passengers: int = Field(default=10_000, ge=100, le=100_000)
    max_attendance_sessions_per_group: int = Field(
        default=10_000,
        ge=100,
        le=100_000,
    )
    # Redis pub/sub carries only lossy invalidation hints. The append-only
    # database cursor remains authoritative, so deployments may explicitly
    # choose a visible cursor-only degradation mode while repairing Redis.
    realtime_enabled: bool = False
    realtime_require_redis: bool = True
    realtime_heartbeat_seconds: int = Field(default=20, ge=5, le=60)
    realtime_idle_timeout_seconds: int = Field(default=65, ge=15, le=180)
    realtime_authorization_refresh_seconds: int = Field(default=60, ge=15, le=300)
    # These two values are process-local safety rails. Deployment-wide
    # admission is enforced by the Redis leases below.
    realtime_max_connections: int = Field(default=5_000, ge=100, le=50_000)
    # Keep handshake database work near the per-process SQL pool width. A much
    # larger value only moves a reconnect storm into the pool wait queue and
    # can starve ordinary dashboard/mobile requests.
    realtime_max_authenticating_connections: int = Field(default=32, ge=10, le=5_000)
    realtime_global_max_connections: int = Field(default=1_000, ge=100, le=50_000)
    realtime_global_max_authenticating_connections: int = Field(
        default=32,
        ge=10,
        le=5_000,
    )
    realtime_lease_ttl_seconds: int = Field(default=90, ge=30, le=300)
    realtime_lease_renew_interval_seconds: int = Field(default=20, ge=5, le=60)
    realtime_max_connections_per_session: int = Field(default=3, ge=1, le=10)
    realtime_max_trips_per_connection: int = Field(default=500, ge=1, le=5_000)
    realtime_max_pending_trips_per_connection: int = Field(default=64, ge=4, le=1_000)
    realtime_publish_queue_size: int = Field(default=20_000, ge=100, le=200_000)
    realtime_send_timeout_seconds: float = Field(default=5.0, ge=1.0, le=15.0)
    # App attestation is deliberately opt-in. ``monitor`` records fixed result
    # codes while preserving workflows; ``enforce`` denies only the explicitly
    # protected high-risk action when a server-verified proof is unavailable.
    app_integrity_mode: Literal["disabled", "monitor", "enforce"] = "disabled"
    app_integrity_challenge_ttl_seconds: int = Field(default=120, ge=30, le=300)
    app_integrity_require_redis: bool = True
    app_integrity_proof_max_bytes: int = Field(default=32_768, ge=4_096, le=65_536)
    play_integrity_package_name: str = Field(
        default="com.globalconnects.groupcompanion",
        min_length=3,
        max_length=255,
    )
    play_integrity_allowed_certificate_digests_json: str | None = Field(
        default=None,
        max_length=4_096,
    )
    play_integrity_require_licensed: bool = True
    play_integrity_required_device_verdict: Literal[
        "MEETS_BASIC_INTEGRITY",
        "MEETS_DEVICE_INTEGRITY",
        "MEETS_STRONG_INTEGRITY",
    ] = "MEETS_DEVICE_INTEGRITY"
    play_integrity_timeout_seconds: float = Field(default=8.0, ge=2.0, le=20.0)
    app_attest_team_id: str | None = Field(default=None, max_length=20)
    app_attest_bundle_id: str = Field(
        default="com.globalconnects.groupcompanion",
        min_length=3,
        max_length=255,
    )
    app_attest_environment: Literal["development", "production"] = "development"
    # Exact iOS 27+ App Attest extension allowlists. Keep them unset until an
    # environment has identified its real distribution lane and CFBundleVersion.
    app_attest_allowed_validation_categories_json: str | None = Field(
        default=None,
        max_length=64,
    )
    app_attest_allowed_bundle_versions_json: str | None = Field(
        default=None,
        max_length=2_048,
    )
    # Explicit production acknowledgement: the strict extension contract is
    # available only on iOS 27+, while this app still supports older iOS.
    app_attest_ios27_extension_rollout_confirmed: bool = False
    admin_page_size: int = Field(default=50, ge=10, le=100)
    common_document_max_bytes: int = Field(
        default=25 * 1024 * 1024,
        ge=1024,
        le=100 * 1024 * 1024,
    )
    personal_document_max_bytes: int = Field(
        default=25 * 1024 * 1024,
        ge=1024,
        le=25 * 1024 * 1024,
    )
    document_grant_ttl_seconds: int = Field(default=60, ge=30, le=300)
    push_provider: Literal["disabled", "expo", "fcm"] = "disabled"
    push_access_token: SecretStr | None = None
    # Must match the Firebase project bundled with the released Android app.
    push_fcm_project_id: Literal["group-companion-c2c30"] = "group-companion-c2c30"
    push_fcm_credentials_file: str | None = Field(default=None, max_length=1024)
    # iOS delivery is independent of Android's provider and uses Apple's APNs directly.
    push_apns_enabled: bool = False
    push_apns_key_file: str | None = Field(default=None, max_length=1024)
    push_apns_key_id: str | None = Field(default=None, pattern=r"^[A-Z0-9]{10}$")
    push_apns_team_id: str | None = Field(default=None, pattern=r"^[A-Z0-9]{10}$")
    push_batch_size: int = Field(default=100, ge=1, le=100)
    push_timeout_seconds: float = Field(default=10.0, ge=1.0, le=30.0)
    push_dispatch_interval_seconds: int = Field(default=5, ge=1, le=300)
    push_max_send_attempts: int = Field(default=5, ge=1, le=10)
    push_retry_base_seconds: int = Field(default=5, ge=1, le=300)
    push_receipt_batch_size: int = Field(default=1_000, ge=1, le=1_000)
    push_receipt_initial_delay_seconds: int = Field(default=900, ge=60, le=3_600)
    push_receipt_poll_interval_seconds: int = Field(default=60, ge=15, le=900)
    push_receipt_max_attempts: int = Field(default=8, ge=1, le=24)
    push_receipt_max_age_hours: int = Field(default=23, ge=1, le=24)
    push_countdown_scan_interval_seconds: int = Field(default=900, ge=60, le=3_600)
    push_countdown_timezone: str = "Asia/Kolkata"
    push_countdown_send_hour: int = Field(default=9, ge=0, le=23)

    @field_validator(
        "jwt_secret_key",
        "offline_lease_private_key_b64",
        "otp_development_code",
        "push_access_token",
        mode="before",
    )
    @classmethod
    def normalize_optional_mobile_secrets(cls, value: object) -> object | None:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "offline_lease_active_kid",
        "offline_lease_public_keys_json",
        "play_integrity_allowed_certificate_digests_json",
        "app_attest_team_id",
        "app_attest_allowed_validation_categories_json",
        "app_attest_allowed_bundle_versions_json",
        "push_fcm_credentials_file",
        mode="before",
    )
    @classmethod
    def normalize_optional_offline_lease_values(cls, value: object) -> object | None:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("offline_lease_issuer", "offline_lease_audience")
    @classmethod
    def validate_offline_lease_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{2,119}", normalized):
            raise ValueError(
                "Mobile offline lease issuer and audience must use a bounded ASCII identifier"
            )
        return normalized

    @field_validator("play_integrity_package_name", "app_attest_bundle_id")
    @classmethod
    def validate_mobile_app_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9]+(?:[.-][A-Za-z0-9_-]+)+", normalized):
            raise ValueError("Mobile app-integrity identifiers must be bounded package IDs")
        return normalized

    @field_validator("app_attest_team_id")
    @classmethod
    def validate_app_attest_team_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{10}", normalized):
            raise ValueError("MOBILE_APP_ATTEST_TEAM_ID must be a 10-character Apple team ID")
        return normalized

    @field_validator("app_attest_allowed_validation_categories_json")
    @classmethod
    def validate_app_attest_validation_categories(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "MOBILE_APP_ATTEST_ALLOWED_VALIDATION_CATEGORIES_JSON must be JSON"
            ) from exc
        if not isinstance(parsed, list) or not 1 <= len(parsed) <= 6:
            raise ValueError(
                "MOBILE_APP_ATTEST_ALLOWED_VALIDATION_CATEGORIES_JSON must contain 1-6 categories"
            )
        categories: set[int] = set()
        for category in parsed:
            if (
                isinstance(category, bool)
                or not isinstance(category, int)
                or category not in {1, 2, 3, 4, 5, 6}
            ):
                raise ValueError(
                    "App Attest validation categories must be explicit Apple categories 1-6"
                )
            categories.add(category)
        return json.dumps(sorted(categories), separators=(",", ":"))

    @field_validator("app_attest_allowed_bundle_versions_json")
    @classmethod
    def validate_app_attest_bundle_versions(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("MOBILE_APP_ATTEST_ALLOWED_BUNDLE_VERSIONS_JSON must be JSON") from exc
        if not isinstance(parsed, list) or not 1 <= len(parsed) <= 64:
            raise ValueError(
                "MOBILE_APP_ATTEST_ALLOWED_BUNDLE_VERSIONS_JSON must contain 1-64 versions"
            )
        versions: set[str] = set()
        for version in parsed:
            if not isinstance(version, str) or not re.fullmatch(
                r"[0-9]{1,8}(?:\.[0-9]{1,8}){0,2}",
                version,
            ):
                raise ValueError(
                    "App Attest bundle versions must be exact bounded CFBundleVersion values"
                )
            versions.add(version)
        return json.dumps(sorted(versions), separators=(",", ":"))

    @field_validator("play_integrity_allowed_certificate_digests_json")
    @classmethod
    def validate_play_certificate_digests(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "MOBILE_PLAY_INTEGRITY_ALLOWED_CERTIFICATE_DIGESTS_JSON must be JSON"
            ) from exc
        if not isinstance(parsed, list) or not 1 <= len(parsed) <= 8:
            raise ValueError(
                "MOBILE_PLAY_INTEGRITY_ALLOWED_CERTIFICATE_DIGESTS_JSON must contain 1-8 digests"
            )
        for digest in parsed:
            if not isinstance(digest, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}=?", digest):
                raise ValueError(
                    "Play signing-certificate digests must be SHA-256 base64url values"
                )
        return json.dumps(sorted(set(parsed)), separators=(",", ":"))

    @model_validator(mode="after")
    def validate_development_otp(self) -> Self:
        if self.otp_provider == "development" and self.otp_development_code is None:
            raise ValueError(
                "MOBILE_OTP_DEVELOPMENT_CODE is required for the development OTP provider"
            )
        return self

    @model_validator(mode="after")
    def validate_push_receipt_window(self) -> Self:
        if self.push_receipt_initial_delay_seconds >= self.push_receipt_max_age_hours * 3_600:
            raise ValueError(
                "MOBILE_PUSH_RECEIPT_INITIAL_DELAY_SECONDS must be shorter than "
                "MOBILE_PUSH_RECEIPT_MAX_AGE_HOURS"
            )
        return self

    @model_validator(mode="after")
    def validate_fcm_credentials_configuration(self) -> Self:
        if self.push_provider == "fcm" and not self.push_fcm_credentials_file:
            raise ValueError(
                "MOBILE_PUSH_FCM_CREDENTIALS_FILE must name the mounted service-account file"
            )
        return self

    @model_validator(mode="after")
    def validate_apns_credentials_configuration(self) -> Self:
        if self.push_apns_enabled and not all(
            (self.push_apns_key_file, self.push_apns_key_id, self.push_apns_team_id)
        ):
            raise ValueError("Enabled APNs requires MOBILE_PUSH_APNS_KEY_FILE, KEY_ID and TEAM_ID")
        return self

    @model_validator(mode="after")
    def validate_realtime_heartbeat_window(self) -> Self:
        if self.realtime_idle_timeout_seconds <= self.realtime_heartbeat_seconds * 2:
            raise ValueError(
                "MOBILE_REALTIME_IDLE_TIMEOUT_SECONDS must exceed two heartbeat intervals"
            )
        return self

    @model_validator(mode="after")
    def validate_realtime_capacity_leases(self) -> Self:
        if self.realtime_lease_ttl_seconds < self.realtime_lease_renew_interval_seconds * 3:
            raise ValueError(
                "MOBILE_REALTIME_LEASE_TTL_SECONDS must cover at least three renewal intervals"
            )
        return self

    @field_validator("push_countdown_timezone")
    @classmethod
    def validate_push_countdown_timezone(cls, value: str) -> str:
        normalized = value.strip()
        try:
            ZoneInfo(normalized)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError(
                "MOBILE_PUSH_COUNTDOWN_TIMEZONE must be a valid IANA timezone"
            ) from exc
        return normalized
