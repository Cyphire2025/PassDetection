from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config.settings import Settings
from app.core.security.identity_security import (
    IdentitySecurityError,
    decrypt_mfa_secret,
    encrypt_mfa_secret,
    generate_mfa_secret,
    generate_recovery_codes,
    hash_identity_action_token,
    hash_identity_value,
    hash_recovery_code,
    identity_action_token_hash_candidates,
    identity_mfa_fernet,
    mfa_ciphertext_key_id,
    reencrypt_mfa_secret_if_needed,
    totp_code,
    verify_totp,
)


def test_totp_accepts_bounded_drift_and_fences_replay() -> None:
    secret = generate_mfa_secret()
    now = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    counter = int(now.timestamp()) // 30
    previous_code = totp_code(secret, counter=counter - 1)

    accepted_counter = verify_totp(secret, previous_code, now=now)

    assert accepted_counter == counter - 1
    assert (
        verify_totp(
            secret,
            previous_code,
            now=now,
            last_accepted_counter=accepted_counter,
        )
        is None
    )
    assert verify_totp(secret, totp_code(secret, counter=counter - 2), now=now) is None


def test_totp_rejects_malformed_secrets_and_codes() -> None:
    with pytest.raises(IdentitySecurityError, match="MFA secret is invalid"):
        totp_code("%%%%", counter=1)

    assert verify_totp(generate_mfa_secret(), "12 456", now=datetime.now(tz=UTC)) is None


def test_mfa_secret_is_encrypted_with_domain_separation(test_settings: Settings) -> None:
    secret = generate_mfa_secret()
    ciphertext = encrypt_mfa_secret(secret, settings=test_settings)

    assert secret not in ciphertext
    assert decrypt_mfa_secret(ciphertext, settings=test_settings) == secret
    assert hash_identity_value(
        "same-value", purpose="activation", settings=test_settings
    ) != hash_identity_value(
        "same-value",
        purpose="password-recovery",
        settings=test_settings,
    )


def test_recovery_codes_are_unique_high_entropy_and_normalized(test_settings: Settings) -> None:
    codes = generate_recovery_codes()

    assert len(codes) == 10
    assert len(set(codes)) == 10
    assert all(len(code.replace("-", "")) == 16 for code in codes)
    canonical_hash = hash_recovery_code(codes[0], user_id="user-1", settings=test_settings)
    normalized_hash = hash_recovery_code(
        codes[0].lower().replace("-", " "),
        user_id="user-1",
        settings=test_settings,
    )
    assert canonical_hash == normalized_hash


def test_identity_token_hash_is_fixed_size_and_does_not_expose_the_token(
    test_settings: Settings,
) -> None:
    raw = "x" * 43
    digest = hash_identity_value(raw, purpose="action-activation", settings=test_settings)

    assert len(digest) == 64
    assert raw not in digest


def test_mfa_keyring_decrypts_legacy_and_lazily_reencrypts_with_active_key(
    test_settings: Settings,
) -> None:
    secret = generate_mfa_secret()
    legacy_ciphertext = (
        identity_mfa_fernet(test_settings).encrypt(secret.encode("ascii")).decode("ascii")
    )
    rotated = test_settings.model_copy(
        update={
            "identity_mfa_encryption_key_id": "mfa-2026-08",
            "identity_mfa_encryption_key": SecretStr("new-mfa-key-material-2026-08"),
            "identity_mfa_decryption_keys": {"legacy-v1": SecretStr(test_settings.app_secret_key)},
        }
    )

    assert decrypt_mfa_secret(legacy_ciphertext, rotated) == secret
    reencrypted = reencrypt_mfa_secret_if_needed(legacy_ciphertext, rotated)
    assert mfa_ciphertext_key_id(reencrypted) == "mfa-2026-08"
    assert decrypt_mfa_secret(reencrypted, rotated) == secret
    assert reencrypt_mfa_secret_if_needed(reencrypted, rotated) == reencrypted

    rollback = test_settings.model_copy(
        update={
            "identity_mfa_decryption_keys": {
                "mfa-2026-08": SecretStr("new-mfa-key-material-2026-08")
            }
        }
    )
    assert decrypt_mfa_secret(reencrypted, rollback) == secret


def test_mfa_keyring_fails_safely_for_unknown_and_corrupted_ciphertext(
    test_settings: Settings,
) -> None:
    with pytest.raises(IdentitySecurityError, match="key is unavailable"):
        decrypt_mfa_secret("idsec:mfa:v2:missing:gAAAA-invalid", test_settings)
    with pytest.raises(IdentitySecurityError, match="could not be decrypted"):
        decrypt_mfa_secret("idsec:mfa:v2:legacy-v1:gAAAA-invalid", test_settings)


def test_action_token_hmac_uses_independent_bounded_rotation_keyring(
    test_settings: Settings,
) -> None:
    raw_token = "one-time-high-entropy-token"
    legacy_hash = hash_identity_action_token(
        raw_token,
        purpose="password_recovery",
        settings=test_settings,
    )
    assert legacy_hash == hash_identity_value(
        raw_token,
        purpose="action-password_recovery",
        settings=test_settings,
    )

    rotated = test_settings.model_copy(
        update={
            "identity_action_hmac_key_id": "actions-2026-08",
            "identity_action_hmac_key": SecretStr("new-action-hmac-material-2026-08"),
            "identity_action_hmac_previous_keys": {
                "legacy-v1": SecretStr(test_settings.app_secret_key)
            },
        }
    )
    candidates = dict(
        identity_action_token_hash_candidates(
            raw_token,
            purpose="password_recovery",
            settings=rotated,
        )
    )

    assert candidates["legacy-v1"] == legacy_hash
    assert candidates["actions-2026-08"] != legacy_hash


def test_identity_keyrings_reject_ambiguous_or_unbounded_previous_keys(
    test_settings: Settings,
) -> None:
    with pytest.raises(ValidationError, match="active key ID must not also be a previous key"):
        Settings(
            app_secret_key=test_settings.app_secret_key,
            identity_mfa_encryption_key_id="mfa-current",
            identity_mfa_encryption_key=SecretStr("current-mfa-key-material"),
            identity_mfa_decryption_keys={
                "mfa-current": SecretStr("ambiguous-previous-key-material")
            },
            _env_file=None,
        )

    with pytest.raises(ValidationError, match="previous key ring exceeds"):
        Settings(
            app_secret_key=test_settings.app_secret_key,
            identity_previous_key_limit=1,
            identity_action_hmac_previous_keys={
                "actions-old-1": SecretStr("first-old-action-key"),
                "actions-old-2": SecretStr("second-old-action-key"),
            },
            _env_file=None,
        )


def test_raw_recovery_token_exposure_setting_is_development_only(
    test_settings: Settings,
) -> None:
    with pytest.raises(ValidationError, match="allowed only in development"):
        Settings(
            app_env="staging",
            app_secret_key=test_settings.app_secret_key,
            password_recovery_development_expose_token=True,
            _env_file=None,
        )
