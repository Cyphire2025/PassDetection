from __future__ import annotations

from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.infrastructure.email.token_encryption import (
    EmailTokenCipher,
    EncryptedToken,
    TokenDecryptionError,
    TokenEncryptionError,
)


def test_token_cipher_round_trip_is_versioned_and_non_exposing() -> None:
    raw_token = "provider-refresh-token-that-must-not-leak"
    cipher = EmailTokenCipher(
        key=Fernet.generate_key().decode("ascii"),
        key_version=7,
    )

    encrypted = cipher.encrypt(raw_token)

    assert encrypted.key_version == 7
    assert encrypted.ciphertext != raw_token
    assert raw_token not in repr(encrypted)
    assert cipher.decrypt(encrypted) == raw_token


def test_token_cipher_loads_secret_settings_without_exposing_key() -> None:
    key = Fernet.generate_key().decode("ascii")
    settings = SimpleNamespace(
        email_token_encryption_key=SecretStr(key),
        email_token_encryption_key_version=3,
        email_token_decryption_keys={},
    )

    cipher = EmailTokenCipher.from_settings(settings)  # type: ignore[arg-type]

    assert cipher.key_version == 3
    assert cipher.decrypt(cipher.encrypt("access-token")) == "access-token"


def test_token_cipher_rejects_wrong_version_and_tampering_safely() -> None:
    cipher = EmailTokenCipher(
        key=Fernet.generate_key().decode("ascii"),
        key_version=2,
    )
    encrypted = cipher.encrypt("sensitive-token")

    with pytest.raises(TokenDecryptionError) as wrong_version:
        cipher.decrypt(
            EncryptedToken(
                ciphertext=encrypted.ciphertext,
                key_version=1,
            )
        )
    with pytest.raises(TokenDecryptionError) as tampered:
        cipher.decrypt(
            EncryptedToken(
                ciphertext=encrypted.ciphertext[:-1] + "A",
                key_version=2,
            )
        )

    assert "sensitive-token" not in str(wrong_version.value)
    assert encrypted.ciphertext not in str(tampered.value)


def test_token_cipher_decrypts_prior_version_during_rotation() -> None:
    old_key = Fernet.generate_key().decode("ascii")
    new_key = Fernet.generate_key().decode("ascii")
    old_cipher = EmailTokenCipher(key=old_key, key_version=1)
    rotating_cipher = EmailTokenCipher(
        key=new_key,
        key_version=2,
        decryption_keys={1: old_key},
    )

    old_token = old_cipher.encrypt("provider-refresh-token")

    assert rotating_cipher.decrypt(old_token) == "provider-refresh-token"
    assert rotating_cipher.encrypt("new-token").key_version == 2


def test_token_cipher_requires_a_valid_configured_key() -> None:
    with pytest.raises(TokenEncryptionError, match="not configured"):
        EmailTokenCipher.from_settings(  # type: ignore[arg-type]
            SimpleNamespace(
                email_token_encryption_key=None,
                email_token_encryption_key_version=1,
                email_token_decryption_keys={},
            )
        )
    with pytest.raises(TokenEncryptionError, match="invalid"):
        EmailTokenCipher(key="not-fernet", key_version=1)
