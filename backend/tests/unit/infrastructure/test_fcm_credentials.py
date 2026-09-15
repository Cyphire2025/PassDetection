"""Synthetic service-account fixtures only; OAuth transport is patched in memory."""

from __future__ import annotations

import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.infrastructure.mobile_push import fcm_credentials

PROJECT = "group-companion-c2c30"


@pytest.fixture
def credential_file(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    info = {
        "type": "service_account",
        "project_id": PROJECT,
        "client_email": f"synthetic@{PROJECT}.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
        "private_key": key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    }
    path = tmp_path / "synthetic-fcm.json"
    path.write_text(json.dumps(info))
    yield path, info
    fcm_credentials._credentials.cache_clear()


async def test_service_account_oauth_token_is_cached_without_calling_a_live_server(
    credential_file, monkeypatch
):
    path, _ = credential_file
    calls = []

    def fake_request(self, url, **kwargs):
        calls.append(url)
        return fcm_credentials._Response(
            httpx.Response(
                200,
                json={
                    "access_token": "synthetic-token",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )
        )

    monkeypatch.setattr(fcm_credentials._Request, "__call__", fake_request)
    for _ in range(2):
        assert (
            await fcm_credentials.fcm_access_token(str(path), PROJECT, timeout=2)
            == "synthetic-token"
        )
    assert calls == ["https://oauth2.googleapis.com/token"]


@pytest.mark.parametrize(
    "key,value",
    [
        ("project_id", "wrong-project"),
        ("type", "authorized_user"),
        ("token_uri", "https://untrusted.example.test/token"),
    ],
)
async def test_credentials_require_expected_project_type_and_fixed_oauth_endpoint(
    credential_file, key, value
):
    path, info = credential_file
    info[key] = value
    path.write_text(json.dumps(info))
    with pytest.raises(fcm_credentials.FcmCredentialError, match="project_or_type_mismatch"):
        await fcm_credentials.fcm_access_token(str(path), PROJECT, timeout=2)


async def test_missing_and_relative_credential_paths_fail_without_disclosing_path(tmp_path):
    with pytest.raises(
        fcm_credentials.FcmCredentialError, match="fcm_credentials_missing"
    ) as error:
        await fcm_credentials.fcm_access_token(
            str(tmp_path / "PRIVATE-name.json"), PROJECT, timeout=2
        )
    assert "PRIVATE" not in str(error.value)
    with pytest.raises(fcm_credentials.FcmCredentialError, match="path_must_be_absolute"):
        await fcm_credentials.fcm_access_token("relative.json", PROJECT, timeout=2)
    with pytest.raises(fcm_credentials.FcmCredentialError, match="fcm_credentials_missing"):
        await fcm_credentials.fcm_access_token(None, PROJECT, timeout=2)


async def test_oversized_or_malformed_credentials_do_not_expose_contents(tmp_path):
    path = tmp_path / "synthetic.json"
    for data in ["PRIVATE malformed", "a" * 65537]:
        path.write_text(data)
        with pytest.raises(
            fcm_credentials.FcmCredentialError, match="fcm_credentials_invalid"
        ) as error:
            await fcm_credentials.fcm_access_token(str(path), PROJECT, timeout=2)
        assert "PRIVATE" not in str(error.value)


async def test_oauth_failure_is_sanitized(credential_file, monkeypatch):
    path, _ = credential_file

    def failed_refresh(self, url, **kwargs):
        raise RuntimeError("PRIVATE provider response and key")

    monkeypatch.setattr(fcm_credentials._Request, "__call__", failed_refresh)
    with pytest.raises(
        fcm_credentials.FcmCredentialError, match="fcm_credentials_unavailable"
    ) as error:
        await fcm_credentials.fcm_access_token(str(path), PROJECT, timeout=2)
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize(
    "status,retryable",
    [(429, True), (500, True), (503, True), (401, False), (403, False), (400, False)],
)
async def test_oauth_http_classification_distinguishes_temporary_outage_from_bad_credentials(
    credential_file,
    monkeypatch,
    status,
    retryable,
):
    path, _ = credential_file
    original_client = httpx.Client
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(
            status, json={"error": "invalid_grant", "error_description": "PRIVATE detail"}
        )

    monkeypatch.setattr(
        fcm_credentials.httpx,
        "Client",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
    )
    with pytest.raises(fcm_credentials.FcmCredentialError) as error:
        await fcm_credentials.fcm_access_token(str(path), PROJECT, timeout=2)
    assert error.value.retryable is retryable
    assert error.value.code == (
        "fcm_credentials_unavailable" if retryable else "fcm_authentication_failed"
    )
    assert "PRIVATE" not in str(error.value)
    assert calls == ["https://oauth2.googleapis.com/token"]


async def test_oauth_transport_timeout_is_safe_to_retry_before_any_message_send(
    credential_file, monkeypatch
):
    path, _ = credential_file
    original_client = httpx.Client

    def handler(request):
        raise httpx.ReadTimeout("PRIVATE network detail", request=request)

    monkeypatch.setattr(
        fcm_credentials.httpx,
        "Client",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
    )
    with pytest.raises(fcm_credentials.FcmCredentialError) as error:
        await fcm_credentials.fcm_access_token(str(path), PROJECT, timeout=2)
    assert error.value.retryable
    assert error.value.code == "fcm_credentials_unavailable"
    assert "PRIVATE" not in str(error.value)
