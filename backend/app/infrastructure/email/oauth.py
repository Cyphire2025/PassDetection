"""OAuth state and PKCE primitives for server-side email connections."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field

_PKCE_VERIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
_STATE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,512}$")
_SHA256_HEX_PATTERN = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True, slots=True)
class PkcePair:
    verifier: str = field(repr=False)
    challenge: str


def generate_pkce_pair() -> PkcePair:
    """Generate an RFC 7636 S256 verifier/challenge pair."""

    verifier = secrets.token_urlsafe(64)
    return PkcePair(
        verifier=verifier,
        challenge=build_pkce_challenge(verifier),
    )


def build_pkce_challenge(verifier: str) -> str:
    """Build a base64url-without-padding SHA-256 PKCE challenge."""

    if not _PKCE_VERIFIER_PATTERN.fullmatch(verifier):
        raise ValueError("PKCE verifier must be 43-128 URL-safe characters")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def generate_oauth_state() -> str:
    """Generate a high-entropy state value for single-use server-side storage."""

    return secrets.token_urlsafe(32)


def hash_oauth_state(state: str) -> str:
    """Hash state before persistence so a database read cannot replay it."""

    if not _STATE_PATTERN.fullmatch(state):
        raise ValueError("OAuth state must be a URL-safe value")
    return hashlib.sha256(state.encode("ascii")).hexdigest()


def oauth_state_matches(state: str, expected_digest: str) -> bool:
    """Compare a callback state with a persisted digest in constant time."""

    if not _STATE_PATTERN.fullmatch(state):
        return False
    if not _SHA256_HEX_PATTERN.fullmatch(expected_digest):
        return False
    actual_digest = hashlib.sha256(state.encode("ascii")).hexdigest()
    return hmac.compare_digest(actual_digest, expected_digest)
