"""Cross-setting startup admission checks; called in the public model order."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, TypeVar

from app.core.security.mobile_offline_lease import (
    validate_mobile_offline_lease_signing_configuration,
)

if TYPE_CHECKING:
    from app.core.config.settings import Settings

_SettingsT = TypeVar("_SettingsT", bound="Settings")


def validate_mobile_otp_configuration(settings: _SettingsT) -> _SettingsT:
    mobile = settings.mobile
    if settings.is_production and mobile.otp_provider == "development":
        raise ValueError("MOBILE_OTP_PROVIDER=development is forbidden when APP_ENV=production")
    if mobile.otp_provider != "whatsapp":
        return settings

    missing: list[str] = []
    if not (settings.whatsapp_access_token or "").strip():
        missing.append("WHATSAPP_ACCESS_TOKEN")
    if not (settings.whatsapp_phone_number_id or "").strip():
        missing.append("WHATSAPP_PHONE_NUMBER_ID")
    if not settings.whatsapp_otp_template_name:
        missing.append("WHATSAPP_OTP_TEMPLATE_NAME")
    if missing:
        raise ValueError("MOBILE_OTP_PROVIDER=whatsapp requires " + ", ".join(missing))
    return settings


def validate_mobile_production_signing_secret(settings: _SettingsT) -> _SettingsT:
    """Fail startup before a weak production mobile signing key can be used."""

    mobile = settings.mobile
    if not (settings.is_production and mobile.enabled):
        return settings
    configured = mobile.jwt_secret_key
    secret = configured.get_secret_value() if configured is not None else ""
    if len(secret.encode("utf-8")) < 32:
        raise ValueError(
            "MOBILE_JWT_SECRET_KEY must contain at least 32 bytes when the mobile API "
            "is enabled in production"
        )
    return settings


def validate_mobile_offline_lease_signing_keys(settings: _SettingsT) -> _SettingsT:
    """Fail closed outside development when mobile offline auth cannot be verified."""

    mobile = settings.mobile
    if settings.app_env == "development" or not mobile.enabled:
        return settings
    private_key_b64 = (
        mobile.offline_lease_private_key_b64.get_secret_value().strip()
        if mobile.offline_lease_private_key_b64 is not None
        else None
    )
    validate_mobile_offline_lease_signing_configuration(
        active_kid=mobile.offline_lease_active_kid,
        private_key_b64=private_key_b64,
        public_keys_json=mobile.offline_lease_public_keys_json,
    )
    return settings


def validate_mobile_verified_link_configuration(settings: _SettingsT) -> _SettingsT:
    """Keep the production Android association document available and exact."""

    mobile = settings.mobile
    if not (settings.is_production and mobile.enabled):
        return settings
    if mobile.play_integrity_package_name != "com.globalconnects.groupcompanion":
        raise ValueError(
            "MOBILE_PLAY_INTEGRITY_PACKAGE_NAME must equal the production Android "
            "package com.globalconnects.groupcompanion"
        )
    if mobile.play_integrity_allowed_certificate_digests_json is None:
        raise ValueError(
            "MOBILE_PLAY_INTEGRITY_ALLOWED_CERTIFICATE_DIGESTS_JSON is required "
            "for production Android verified links"
        )
    return settings


def validate_mobile_app_integrity_configuration(settings: _SettingsT) -> _SettingsT:
    """Reject an enforcement rollout that lacks cross-worker/provider bindings."""

    mobile = settings.mobile
    if mobile.app_integrity_mode == "disabled" or not mobile.enabled:
        return settings
    if mobile.app_integrity_mode == "enforce" and not mobile.app_integrity_require_redis:
        raise ValueError(
            "MOBILE_APP_INTEGRITY_REQUIRE_REDIS must be true when integrity is enforced"
        )
    if not settings.is_production or mobile.app_integrity_mode != "enforce":
        return settings
    if mobile.play_integrity_allowed_certificate_digests_json is None:
        raise ValueError(
            "MOBILE_PLAY_INTEGRITY_ALLOWED_CERTIFICATE_DIGESTS_JSON is required "
            "for production enforcement"
        )
    if mobile.app_attest_team_id is None:
        raise ValueError("MOBILE_APP_ATTEST_TEAM_ID is required for production enforcement")
    if mobile.app_attest_environment != "production":
        raise ValueError(
            "MOBILE_APP_ATTEST_ENVIRONMENT must be production for production enforcement"
        )
    if not mobile.app_attest_ios27_extension_rollout_confirmed:
        raise ValueError(
            "MOBILE_APP_ATTEST_IOS27_EXTENSION_ROLLOUT_CONFIRMED must be true "
            "only after the iOS 27 minimum-version or adoption gate is complete"
        )
    if mobile.app_attest_allowed_validation_categories_json is None:
        raise ValueError(
            "MOBILE_APP_ATTEST_ALLOWED_VALIDATION_CATEGORIES_JSON is required "
            "for production enforcement"
        )
    allowed_categories: object = json.loads(
        mobile.app_attest_allowed_validation_categories_json
    )
    if not isinstance(allowed_categories, list) or not set(allowed_categories).issubset(
        {2, 4, 5}
    ):
        raise ValueError(
            "Production iOS App Attest categories must be TestFlight, App Store, "
            "or approved enterprise/ad-hoc distribution (2, 4, or 5)"
        )
    if mobile.app_attest_allowed_bundle_versions_json is None:
        raise ValueError(
            "MOBILE_APP_ATTEST_ALLOWED_BUNDLE_VERSIONS_JSON is required "
            "for production enforcement"
        )
    return settings
