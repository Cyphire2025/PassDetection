"""
Password Hashing Utilities
==========================
Wraps bcrypt directly for consistent password hashing across the platform.

Rules:
  - Never store or log plaintext passwords.
  - Always verify using this module — never compare strings directly.
"""

import re

import bcrypt

PASSWORD_MIN_LENGTH = 10


def validate_password_strength(password: str) -> None:
    """Enforce the shared password policy for account creation and reset."""
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must include an uppercase letter")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must include a lowercase letter")
    if not re.search(r"\d", password):
        raise ValueError("Password must include a number")


def hash_password(plain_password: str) -> str:
    """
    Hash a plaintext password using bcrypt.

    Args:
        plain_password: The user-supplied password in plaintext.

    Returns:
        A bcrypt hash string safe to store in the database.
    """
    validate_password_strength(plain_password)
    pwd_bytes = plain_password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plaintext password against a stored bcrypt hash.

    Args:
        plain_password:   The password supplied during login.
        hashed_password:  The hash retrieved from the database.

    Returns:
        True if the password matches the hash, False otherwise.
    """
    pwd_bytes = plain_password.encode("utf-8")
    hashed_bytes = hashed_password.encode("utf-8")
    try:
        return bcrypt.checkpw(pwd_bytes, hashed_bytes)
    except Exception:
        return False
