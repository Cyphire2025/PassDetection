from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

import pytest

from app.domain.value_objects.tokens import AccessToken, RefreshTokenValue, TokenPair


@pytest.mark.parametrize("token_type", [AccessToken, RefreshTokenValue])
def test_token_repr_omits_credentials_without_changing_expiry_or_transport(
    token_type: type[AccessToken] | type[RefreshTokenValue],
) -> None:
    expires = datetime(2030, 1, 1, tzinfo=UTC)
    token = token_type(token="synthetic-sensitive-token", expires_at=expires)

    assert "synthetic-sensitive-token" not in repr(token)
    assert token.token == "synthetic-sensitive-token"
    assert token.expires_at == expires
    assert asdict(token)["token"] == "synthetic-sensitive-token"


def test_nested_token_pair_repr_omits_both_credentials() -> None:
    expires = datetime(2030, 1, 1, tzinfo=UTC)
    pair = TokenPair(
        AccessToken("synthetic-access-token", expires),
        RefreshTokenValue("synthetic-refresh-token", expires),
    )

    assert "synthetic-access-token" not in repr(pair)
    assert "synthetic-refresh-token" not in repr(pair)
