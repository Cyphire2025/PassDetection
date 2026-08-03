from __future__ import annotations

import uuid
from dataclasses import replace
from types import SimpleNamespace

import jwt
import pytest

from app.core.security import mobile_jwt
from app.domain.exceptions.exceptions import AuthenticationError, TokenExpiredError


def _unverified_claims(token: str) -> dict[str, object]:
    return jwt.decode(
        token,
        options={
            "verify_signature": False,
            "verify_exp": False,
            "verify_aud": False,
            "verify_iss": False,
        },
    )


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        app_secret_key="dashboard-test-secret",
        is_production=False,
        mobile=SimpleNamespace(
            jwt_secret_key=None,
            jwt_issuer="passdetection-test",
            jwt_audience="gc-mobile-test",
            access_token_expire_minutes=15,
            refresh_token_expire_days=30,
            document_grant_ttl_seconds=60,
            enabled=True,
        ),
    )


def test_mobile_access_token_has_separate_type_and_restriction(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    monkeypatch.setattr(mobile_jwt, "get_settings", lambda: settings)
    principal_id = uuid.uuid4()
    account_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    session_id = uuid.uuid4()

    token, expires_at = mobile_jwt.create_mobile_access_token(
        principal_id=principal_id,
        account_id=account_id,
        principal_type="client_manager",
        agency_id=agency_id,
        session_id=session_id,
        session_generation=3,
        password_change_required=True,
    )

    claims = mobile_jwt.decode_mobile_access_token(token)
    assert claims.principal_id == principal_id
    assert claims.account_id == account_id
    assert claims.agency_id == agency_id
    assert claims.session_id == session_id
    assert claims.session_generation == 3
    assert claims.password_change_required is True
    assert claims.expires_at == expires_at
    unverified = _unverified_claims(token)
    assert unverified["type"] == "mobile_access"
    assert unverified["aud"] == "gc-mobile-test"


def test_mobile_decoder_rejects_wrong_audience(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    monkeypatch.setattr(mobile_jwt, "get_settings", lambda: settings)
    token, _ = mobile_jwt.create_mobile_access_token(
        principal_id=uuid.uuid4(),
        principal_type="passenger",
        agency_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        session_generation=1,
    )
    settings.mobile.jwt_audience = "different-audience"

    with pytest.raises(AuthenticationError):
        mobile_jwt.decode_mobile_access_token(token)


def test_mobile_decoder_preserves_pre_account_namespace_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    monkeypatch.setattr(mobile_jwt, "get_settings", lambda: settings)
    principal_id = uuid.uuid4()
    token, _ = mobile_jwt.create_mobile_access_token(
        principal_id=principal_id,
        principal_type="passenger",
        agency_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        session_generation=1,
    )
    payload = _unverified_claims(token)
    payload.pop("aid")
    legacy_token = jwt.encode(
        payload,
        mobile_jwt._mobile_secret(purpose="access"),
        algorithm="HS256",
    )

    claims = mobile_jwt.decode_mobile_access_token(legacy_token)

    assert claims.account_id == principal_id


def test_refresh_token_is_opaque_and_only_hash_is_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    monkeypatch.setattr(mobile_jwt, "get_settings", lambda: settings)
    token, _ = mobile_jwt.create_mobile_refresh_token()

    digest = mobile_jwt.hash_mobile_refresh_token(token)
    assert token not in digest
    assert len(digest) == 64
    assert mobile_jwt.hash_mobile_refresh_token(token) == digest


def test_document_grant_is_short_lived_and_bound_to_live_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    monkeypatch.setattr(mobile_jwt, "get_settings", lambda: settings)
    claims = mobile_jwt.MobileAccessClaims(
        principal_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        principal_type="passenger",
        agency_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        session_generation=4,
        password_change_required=False,
        expires_at=mobile_jwt.datetime.now(tz=mobile_jwt.UTC),
    )
    access_id = uuid.uuid4()
    group_id = uuid.uuid4()
    document_id = uuid.uuid4()
    passenger_identity_id = claims.principal_id

    token, expires_at = mobile_jwt.create_mobile_document_grant(
        claims=claims,
        gc_group_access_id=access_id,
        group_id=group_id,
        access_generation=7,
        document_id=document_id,
        document_version=2,
        document_scope="personal",
        passenger_identity_id=passenger_identity_id,
    )
    grant = mobile_jwt.decode_mobile_document_grant(token)

    assert (expires_at - mobile_jwt.datetime.now(tz=mobile_jwt.UTC)).total_seconds() <= 60
    mobile_jwt.validate_mobile_document_grant(
        grant,
        access_claims=claims,
        gc_group_access_id=access_id,
        group_id=group_id,
        access_generation=7,
        document_id=document_id,
        document_version=2,
        document_scope="personal",
        passenger_identity_id=passenger_identity_id,
    )


@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("session_id", uuid.uuid4()),
        ("access_generation", 8),
        ("document_scope", "common"),
    ],
)
def test_document_grant_rejects_context_swapping(
    monkeypatch: pytest.MonkeyPatch,
    override: str,
    value: object,
) -> None:
    settings = _settings()
    monkeypatch.setattr(mobile_jwt, "get_settings", lambda: settings)
    claims = mobile_jwt.MobileAccessClaims(
        principal_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        principal_type="passenger",
        agency_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        session_generation=2,
        password_change_required=False,
        expires_at=mobile_jwt.datetime.now(tz=mobile_jwt.UTC),
    )
    context = {
        "gc_group_access_id": uuid.uuid4(),
        "group_id": uuid.uuid4(),
        "access_generation": 3,
        "document_id": uuid.uuid4(),
        "document_version": 1,
        "document_scope": "personal",
        "passenger_identity_id": claims.principal_id,
    }
    token, _ = mobile_jwt.create_mobile_document_grant(claims=claims, **context)
    grant = mobile_jwt.decode_mobile_document_grant(token)
    if override == "session_id":
        assert isinstance(value, uuid.UUID)
        claims = replace(claims, session_id=value)
    else:
        context[override] = value

    with pytest.raises(AuthenticationError):
        mobile_jwt.validate_mobile_document_grant(
            grant,
            access_claims=claims,
            **context,
        )


def test_expired_document_grant_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    monkeypatch.setattr(mobile_jwt, "get_settings", lambda: settings)
    claims = mobile_jwt.MobileAccessClaims(
        principal_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        principal_type="passenger",
        agency_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        session_generation=1,
        password_change_required=False,
        expires_at=mobile_jwt.datetime.now(tz=mobile_jwt.UTC),
    )
    token, _ = mobile_jwt.create_mobile_document_grant(
        claims=claims,
        gc_group_access_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        access_generation=1,
        document_id=uuid.uuid4(),
        document_version=1,
        document_scope="personal",
        passenger_identity_id=claims.principal_id,
    )
    payload = _unverified_claims(token)
    payload["exp"] = 1
    expired = jwt.encode(
        payload,
        mobile_jwt._mobile_secret(purpose="document"),
        algorithm="HS256",
    )

    with pytest.raises(TokenExpiredError):
        mobile_jwt.decode_mobile_document_grant(expired)
