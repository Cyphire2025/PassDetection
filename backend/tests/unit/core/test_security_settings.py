from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.config.settings import JWTSettings, MobileSettings, Settings

_STRONG_APP_SECRET = "9Wv!mR3#kP7@xN2$zQ8&bL5^tY4*cH6+"


def test_jwt_algorithm_is_pinned_to_reviewed_hs256_profile() -> None:
    assert JWTSettings(_env_file=None).algorithm == "HS256"

    with pytest.raises(PydanticValidationError):
        JWTSettings(algorithm="ES256", _env_file=None)  # type: ignore[arg-type]


def test_mobile_settings_accept_whatsapp_without_development_code() -> None:
    settings = MobileSettings(otp_provider="whatsapp", _env_file=None)

    assert settings.otp_provider == "whatsapp"
    assert settings.otp_development_code is None


def test_mobile_push_receipt_polling_must_start_before_receipt_retention_expires() -> None:
    with pytest.raises(
        PydanticValidationError,
        match="MOBILE_PUSH_RECEIPT_INITIAL_DELAY_SECONDS",
    ):
        MobileSettings(
            push_receipt_initial_delay_seconds=3_600,
            push_receipt_max_age_hours=1,
            _env_file=None,
        )


def test_mobile_countdown_timezone_must_be_an_iana_timezone() -> None:
    with pytest.raises(
        PydanticValidationError,
        match="MOBILE_PUSH_COUNTDOWN_TIMEZONE",
    ):
        MobileSettings(
            push_countdown_timezone="not/a-timezone",
            _env_file=None,
        )


@pytest.mark.parametrize("secret", [None, "short-mobile-secret"])
def test_production_mobile_api_rejects_missing_or_weak_signing_secret(
    monkeypatch: pytest.MonkeyPatch,
    secret: str | None,
) -> None:
    monkeypatch.setenv("MOBILE_ENABLED", "true")
    if secret is None:
        monkeypatch.delenv("MOBILE_JWT_SECRET_KEY", raising=False)
    else:
        monkeypatch.setenv("MOBILE_JWT_SECRET_KEY", secret)

    with pytest.raises(PydanticValidationError, match="at least 32 bytes"):
        Settings(
            app_env="production",
            app_secret_key=_STRONG_APP_SECRET,
            _env_file=None,
        )


def test_production_mobile_api_accepts_independent_high_entropy_signing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOBILE_ENABLED", "true")
    monkeypatch.setenv(
        "MOBILE_JWT_SECRET_KEY",
        "9Wv!mR3#kP7@xN2$zQ8&bL5^tY4*cH6+",
    )

    settings = Settings(
        app_env="production",
        app_secret_key=_STRONG_APP_SECRET,
        _env_file=None,
    )

    assert settings.mobile.jwt_secret_key is not None


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_non_development_mobile_api_requires_valid_offline_ed25519_configuration(
    monkeypatch: pytest.MonkeyPatch,
    app_env: str,
) -> None:
    monkeypatch.setenv("MOBILE_ENABLED", "true")
    monkeypatch.setenv(
        "MOBILE_JWT_SECRET_KEY",
        "9Wv!mR3#kP7@xN2$zQ8&bL5^tY4*cH6+",
    )
    monkeypatch.delenv("MOBILE_OFFLINE_LEASE_ACTIVE_KID", raising=False)
    monkeypatch.delenv("MOBILE_OFFLINE_LEASE_PRIVATE_KEY_B64", raising=False)
    monkeypatch.delenv("MOBILE_OFFLINE_LEASE_PUBLIC_KEYS_JSON", raising=False)

    with pytest.raises(
        PydanticValidationError,
        match="MOBILE_OFFLINE_LEASE_ACTIVE_KID",
    ):
        Settings(
            app_env=app_env,  # type: ignore[arg-type]
            app_secret_key=_STRONG_APP_SECRET,
            _env_file=None,
        )


@pytest.mark.parametrize("app_env", ["staging", "production"])
@pytest.mark.parametrize(
    "secret",
    [
        "short-secret",
        "CHANGE_ME_USE_openssl_rand_hex_32",
    ],
)
def test_non_development_rejects_weak_dashboard_signing_secret(
    app_env: str,
    secret: str,
) -> None:
    with pytest.raises(PydanticValidationError, match="APP_SECRET_KEY"):
        Settings(
            app_env=app_env,  # type: ignore[arg-type]
            app_secret_key=secret,
            _env_file=None,
        )


def test_development_otp_provider_is_rejected_at_production_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOBILE_OTP_PROVIDER", "development")
    monkeypatch.setenv("MOBILE_OTP_DEVELOPMENT_CODE", "123456")

    with pytest.raises(PydanticValidationError, match="forbidden"):
        Settings(
            app_env="production",
            app_secret_key=_STRONG_APP_SECRET,
            _env_file=None,
        )


@pytest.mark.parametrize(
    ("overrides", "missing_setting"),
    [
        ({"whatsapp_access_token": None}, "WHATSAPP_ACCESS_TOKEN"),
        ({"whatsapp_phone_number_id": None}, "WHATSAPP_PHONE_NUMBER_ID"),
        ({"whatsapp_otp_template_name": ""}, "WHATSAPP_OTP_TEMPLATE_NAME"),
    ],
)
def test_whatsapp_otp_configuration_fails_closed_when_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, str | None],
    missing_setting: str,
) -> None:
    monkeypatch.setenv("MOBILE_OTP_PROVIDER", "whatsapp")

    values: dict[str, str | None] = {
        "whatsapp_access_token": "provider-token",
        "whatsapp_phone_number_id": "123456789",
        "whatsapp_otp_template_name": "verify_code_1",
        **overrides,
    }
    with pytest.raises(PydanticValidationError, match=missing_setting):
        Settings(
            app_secret_key="unit-test-secret",
            _env_file=None,
            **values,
        )


def test_whatsapp_otp_configuration_accepts_complete_approved_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOBILE_OTP_PROVIDER", "whatsapp")

    settings = Settings(
        app_secret_key="unit-test-secret",
        whatsapp_access_token="provider-token",
        whatsapp_phone_number_id="123456789",
        whatsapp_otp_template_name="verify_code_1",
        whatsapp_otp_template_language="en_US",
        _env_file=None,
    )

    assert settings.mobile.otp_provider == "whatsapp"
    assert settings.whatsapp_otp_template_name == "verify_code_1"


def test_whatsapp_otp_template_name_rejects_unapproved_character_shape() -> None:
    with pytest.raises(PydanticValidationError, match="lowercase letters"):
        Settings(
            app_secret_key="unit-test-secret",
            whatsapp_otp_template_name="Verify Code 1",
            _env_file=None,
        )
