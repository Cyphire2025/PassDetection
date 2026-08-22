from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.config.settings import Settings
from app.core.security.identity_security import (
    IdentitySecurityError,
    decrypt_mfa_secret,
    encrypt_mfa_secret,
    generate_mfa_secret,
    generate_recovery_codes,
    hash_identity_value,
    hash_recovery_code,
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
    assert hash_identity_value("same-value", purpose="activation", settings=test_settings) != hash_identity_value(
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
