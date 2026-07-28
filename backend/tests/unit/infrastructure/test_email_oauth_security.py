from __future__ import annotations

import base64
import hashlib

import pytest

from app.infrastructure.email.oauth import (
    build_pkce_challenge,
    generate_oauth_state,
    generate_pkce_pair,
    hash_oauth_state,
    oauth_state_matches,
)


def test_pkce_pair_uses_s256_and_hides_verifier_from_repr() -> None:
    pair = generate_pkce_pair()

    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(pair.verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    assert len(pair.verifier) >= 43
    assert pair.challenge == expected
    assert pair.verifier not in repr(pair)


def test_pkce_rejects_short_or_non_url_safe_verifier() -> None:
    with pytest.raises(ValueError, match="43-128"):
        build_pkce_challenge("short")
    with pytest.raises(ValueError, match="43-128"):
        build_pkce_challenge("x" * 42 + "+")


def test_oauth_state_is_hashable_and_compared_in_constant_time_contract() -> None:
    state = generate_oauth_state()
    digest = hash_oauth_state(state)

    assert state not in digest
    assert oauth_state_matches(state, digest)
    assert not oauth_state_matches(generate_oauth_state(), digest)
    assert not oauth_state_matches(state, "not-a-sha256-digest")
    assert not oauth_state_matches("bad state", digest)
