from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.core.config.settings import MobileSettings, Settings

_STRONG_APP_SECRET = "app-secret-with-more-than-thirty-two-bytes-2026"
_STRONG_MOBILE_SECRET = "mobile-secret-with-more-than-thirty-two-bytes-2026"
_CERTIFICATE_DIGEST = "C" * 43


def test_play_certificate_allowlist_is_bounded_and_canonical() -> None:
    settings = MobileSettings(
        play_integrity_allowed_certificate_digests_json=json.dumps(
            [f"{_CERTIFICATE_DIGEST}=", "A" * 43, "A" * 43]
        ),
        _env_file=None,
    )

    assert settings.play_integrity_allowed_certificate_digests_json == json.dumps(
        ["A" * 43, f"{_CERTIFICATE_DIGEST}="],
        separators=(",", ":"),
    )

    for invalid in (
        "[]",
        json.dumps(["not-a-sha256-digest"]),
        json.dumps(["A" * 43] * 9),
        '{"digest":"value"}',
    ):
        with pytest.raises(ValidationError, match="certificate|digests"):
            MobileSettings(
                play_integrity_allowed_certificate_digests_json=invalid,
                _env_file=None,
            )


def _base_enforcement_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOBILE_ENABLED", "true")
    monkeypatch.setenv("MOBILE_JWT_SECRET_KEY", _STRONG_MOBILE_SECRET)
    monkeypatch.setenv("MOBILE_APP_INTEGRITY_MODE", "enforce")
    monkeypatch.setenv("MOBILE_APP_INTEGRITY_REQUIRE_REDIS", "true")
    monkeypatch.delenv(
        "MOBILE_PLAY_INTEGRITY_ALLOWED_CERTIFICATE_DIGESTS_JSON",
        raising=False,
    )
    monkeypatch.delenv("MOBILE_APP_ATTEST_TEAM_ID", raising=False)
    monkeypatch.delenv(
        "MOBILE_APP_ATTEST_ALLOWED_VALIDATION_CATEGORIES_JSON",
        raising=False,
    )
    monkeypatch.delenv(
        "MOBILE_APP_ATTEST_ALLOWED_BUNDLE_VERSIONS_JSON",
        raising=False,
    )
    monkeypatch.delenv(
        "MOBILE_APP_ATTEST_IOS27_EXTENSION_ROLLOUT_CONFIRMED",
        raising=False,
    )
    monkeypatch.setenv("MOBILE_APP_ATTEST_ENVIRONMENT", "development")


def test_production_enforcement_rejects_incomplete_provider_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _base_enforcement_environment(monkeypatch)

    with pytest.raises(ValidationError, match="ALLOWED_CERTIFICATE_DIGESTS_JSON"):
        Settings(
            app_env="production",
            app_secret_key=_STRONG_APP_SECRET,
            _env_file=None,
        )

    monkeypatch.setenv(
        "MOBILE_PLAY_INTEGRITY_ALLOWED_CERTIFICATE_DIGESTS_JSON",
        json.dumps([_CERTIFICATE_DIGEST]),
    )
    with pytest.raises(ValidationError, match="MOBILE_APP_ATTEST_TEAM_ID"):
        Settings(
            app_env="production",
            app_secret_key=_STRONG_APP_SECRET,
            _env_file=None,
        )

    monkeypatch.setenv("MOBILE_APP_ATTEST_TEAM_ID", "ABCDEFGHIJ")
    with pytest.raises(ValidationError, match="MOBILE_APP_ATTEST_ENVIRONMENT"):
        Settings(
            app_env="production",
            app_secret_key=_STRONG_APP_SECRET,
            _env_file=None,
        )


def test_production_enforcement_accepts_complete_static_identity_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _base_enforcement_environment(monkeypatch)
    monkeypatch.setenv(
        "MOBILE_PLAY_INTEGRITY_ALLOWED_CERTIFICATE_DIGESTS_JSON",
        json.dumps([_CERTIFICATE_DIGEST]),
    )
    monkeypatch.setenv("MOBILE_APP_ATTEST_TEAM_ID", "abcdefghij")
    monkeypatch.setenv("MOBILE_APP_ATTEST_ENVIRONMENT", "production")
    monkeypatch.setenv(
        "MOBILE_APP_ATTEST_IOS27_EXTENSION_ROLLOUT_CONFIRMED",
        "true",
    )
    monkeypatch.setenv(
        "MOBILE_APP_ATTEST_ALLOWED_VALIDATION_CATEGORIES_JSON",
        "[4]",
    )
    monkeypatch.setenv("MOBILE_APP_ATTEST_ALLOWED_BUNDLE_VERSIONS_JSON", '["1"]')

    settings = Settings(
        app_env="production",
        app_secret_key=_STRONG_APP_SECRET,
        _env_file=None,
    )

    assert settings.mobile.app_integrity_mode == "enforce"
    assert settings.mobile.app_integrity_require_redis is True
    assert settings.mobile.app_attest_team_id == "ABCDEFGHIJ"
    assert settings.mobile.app_attest_allowed_validation_categories_json == "[4]"
    assert settings.mobile.app_attest_allowed_bundle_versions_json == '["1"]'
    assert settings.mobile.app_attest_ios27_extension_rollout_confirmed is True


def test_app_attest_extension_allowlists_are_bounded_and_canonical() -> None:
    settings = MobileSettings(
        app_attest_allowed_validation_categories_json="[5,2,4,4]",
        app_attest_allowed_bundle_versions_json='["12.3","1","1"]',
        _env_file=None,
    )

    assert settings.app_attest_allowed_validation_categories_json == "[2,4,5]"
    assert settings.app_attest_allowed_bundle_versions_json == '["1","12.3"]'

    for invalid_categories in ("[]", "[0]", "[7]", "[10]", '["4"]', "{}"):
        with pytest.raises(ValidationError, match="categories|validation categories"):
            MobileSettings(
                app_attest_allowed_validation_categories_json=invalid_categories,
                _env_file=None,
            )

    for invalid_versions in ("[]", '["1-beta"]', '["1.2.3.4"]', "[1]", "{}"):
        with pytest.raises(ValidationError, match="versions|bundle versions"):
            MobileSettings(
                app_attest_allowed_bundle_versions_json=invalid_versions,
                _env_file=None,
            )


def test_production_enforcement_rejects_unsafe_or_missing_apple_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _base_enforcement_environment(monkeypatch)
    monkeypatch.setenv(
        "MOBILE_PLAY_INTEGRITY_ALLOWED_CERTIFICATE_DIGESTS_JSON",
        json.dumps([_CERTIFICATE_DIGEST]),
    )
    monkeypatch.setenv("MOBILE_APP_ATTEST_TEAM_ID", "ABCDEFGHIJ")
    monkeypatch.setenv("MOBILE_APP_ATTEST_ENVIRONMENT", "production")

    with pytest.raises(ValidationError, match="IOS27_EXTENSION_ROLLOUT_CONFIRMED"):
        Settings(
            app_env="production",
            app_secret_key=_STRONG_APP_SECRET,
            _env_file=None,
        )

    monkeypatch.setenv(
        "MOBILE_APP_ATTEST_IOS27_EXTENSION_ROLLOUT_CONFIRMED",
        "true",
    )
    with pytest.raises(ValidationError, match="ALLOWED_VALIDATION_CATEGORIES_JSON"):
        Settings(
            app_env="production",
            app_secret_key=_STRONG_APP_SECRET,
            _env_file=None,
        )

    monkeypatch.setenv("MOBILE_APP_ATTEST_ALLOWED_VALIDATION_CATEGORIES_JSON", "[3]")
    monkeypatch.setenv("MOBILE_APP_ATTEST_ALLOWED_BUNDLE_VERSIONS_JSON", '["1"]')
    with pytest.raises(ValidationError, match="Production iOS App Attest categories"):
        Settings(
            app_env="production",
            app_secret_key=_STRONG_APP_SECRET,
            _env_file=None,
        )


def test_enforcement_always_requires_cross_worker_replay_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOBILE_ENABLED", "true")
    monkeypatch.setenv("MOBILE_APP_INTEGRITY_MODE", "enforce")
    monkeypatch.setenv("MOBILE_APP_INTEGRITY_REQUIRE_REDIS", "false")

    with pytest.raises(ValidationError, match="REQUIRE_REDIS"):
        Settings(
            app_secret_key=_STRONG_APP_SECRET,
            _env_file=None,
        )
