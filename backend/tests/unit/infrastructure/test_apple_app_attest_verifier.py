from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime

import cbor2
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.application.mobile.app_integrity import (
    MobileIntegrityRejected,
    MobileIntegrityUnavailable,
)
from app.core.config.settings import MobileSettings
from app.infrastructure.security.apple_app_attest_verifier import (
    PyAttestAppleAppAttestVerifier,
    _decode_verification_material,
    _encode_verification_material,
    _parse_attestation_auth_data,
)

_APP_ID = "ABCDEFGHIJ.com.globalconnects.groupcompanion"
_CLIENT_DATA = "R" * 43
_APPLE_SAMPLE_APP_ID = "1234567890.com.example.myapp"
_APPLE_SAMPLE_KEY_ID = "zgSY9YSD+7TaDXssY6WlOPVS1K3Lmk+pFhlcSWE+ZV0="
# Public fixture copied from Apple's 2026 Attestation Object Validation Guide.
_APPLE_SAMPLE_AUTH_DATA = (
    "9EZtaPketsEGIMt+Y8coMkRoXuHWRntUFg51MXIFfwNAAAAAAGFwcGF0dGVzdAAAAAAAAAAAIM4E"
    "mPWEg/u02g17LGOlpTj1UtSty5pPqRYZXElhPmVdpQECAyYgASFYIEMyVErPMj23dEQ8qvM59W5+"
    "lcck+sLBQlnzZeJEVlCyIlggtfsoW89Um8tgWUQS52gqJCfuran7Ut/tCxqxftCfqb2id2FwcGxl"
    "X2J1bmRsZV92ZXJzaW9uXzAxYTF4HGFwcGxlX3ZhbGlkYXRpb25fY2F0ZWdvcnlfMDFEAQAAAA=="
)
_APPLE_SAMPLE_LEAF_CERTIFICATE = (
    "MIIEHTCCA6OgAwIBAgIGAZ2xPwtOMAoGCCqGSM49BAMCME8xIzAhBgNVBAMMGkFwcGxlIEFwcCBB"
    "dHRlc3RhdGlvbiBDQSAxMRMwEQYDVQQKDApBcHBsZSBJbmMuMRMwEQYDVQQIDApDYWxpZm9ybmlh"
    "MB4XDTI2MDQyMDE4MTMxMloXDTI2MDQyMzE4MTMxMlowgZExSTBHBgNVBAMMQGNlMDQ5OGY1ODQ4"
    "M2ZiYjRkYTBkN2IyYzYzYTVhNTM4ZjU1MmQ0YWRjYjlhNGZhOTE2MTk1YzQ5NjEzZTY1NWQxGjAY"
    "BgNVBAsMEUFBQSBDZXJ0aWZpY2F0aW9uMRMwEQYDVQQKDApBcHBsZSBJbmMuMRMwEQYDVQQIDApD"
    "YWxpZm9ybmlhMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEQzJUSs8yPbd0RDyq8zn1bn6VxyT6"
    "wsFCWfNl4kRWULK1+yhbz1Sby2BZRBLnaCokJ+6tqftS3+0LGrF+0J+pvaOCAiYwggIiMAwGA1Ud"
    "EwEB/wQCMAAwDgYDVR0PAQH/BAQDAgTwMBQGA1UdJQQNMAsGCSqGSIb3Y2QEGDB6BgkqhkiG92Nk"
    "CAUEbTBrpAMCAQq/iTADAgEAv4kxAwIBAL+JMgMCAQC/iTMDAgEAv4k0HgQcMTIzNDU2Nzg5MC5j"
    "b20uZXhhbXBsZS5teWFwcL+JNgMCAQS/iTcDAgEAv4k5AwIBAL+JOgMCAQC/iTsDAgEAqgMCAQAw"
    "geAGCSqGSIb3Y2QIBwSB0jCBz7+KeAYEBDI3LjC/iFADAgECv4p5CQQHMS4wLjIxNr+KewkEBzI0"
    "QTMyNWK/inwGBAQyNy4wv4p9BgQEMjcuML+KfgMCAQC/in8DAgEAv4sAAwIBAL+LAQMCAQC/iwID"
    "AgEAv4sDAwIBAL+LBAMCAQG/iwUDAgEAv4sKEAQOMjQuMS4zMjUuMC4yLDC/iwsQBA4yNC4xLjMy"
    "NS4wLjIsML+LDBAEDjI0LjEuMzI1LjAuMiwwv4gCCgQIaXBob25lb3O/iAUKBAhJbnRlcm5hbDAz"
    "BgkqhkiG92NkCAIEJjAkoSIEIIe30G2TpClORvAR5mtsxADwurIHKZdsYZWAtCrmC/9uMFgGCSqG"
    "SIb3Y2QIBgRLMEmjRwRFMEMMAjExMD0wCgwDb2tkoQMBAf8wCQwCb2GhAwEB/zALDARvc2duoQMB"
    "Af8wCwwEb2RlbKEDAQH/MAoMA29ja6EDAQH/MAoGCCqGSM49BAMCA2gAMGUCMCG8x2j20SnJtrGu"
    "Cbw1sk1+NMs/VNm8sRcU4aPhyDNB3mMBdxy8gNza6r91g8v1HQIxAKTqMS+83kFdMob2rD3t9fnN"
    "WWLhA8RFOqw64XhXFTEWXqb1ddPoRcYCFlTEqULtPQ=="
)
_APPLE_SAMPLE_RECEIPT = (
    "MIAGCSqGSIb3DQEHAqCAMIACAQExDzANBglghkgBZQMEAgEFADCABgkqhkiG9w0BBwGggCSABIID6DGCBUEwJAIBAgIBAQQc"
    "MTIzNDU2Nzg5MC5jb20uZXhhbXBsZS5teWFwcDCCBCsCAQMCAQEEggQhMIIEHTCCA6OgAwIBAgIGAZ2xPwtOMAoGCCqGSM49"
    "BAMCME8xIzAhBgNVBAMMGkFwcGxlIEFwcCBBdHRlc3RhdGlvbiBDQSAxMRMwEQYDVQQKDApBcHBsZSBJbmMuMRMwEQYDVQQI"
    "DApDYWxpZm9ybmlhMB4XDTI2MDQyMDE4MTMxMloXDTI2MDQyMzE4MTMxMlowgZExSTBHBgNVBAMMQGNlMDQ5OGY1ODQ4M2Zi"
    "YjRkYTBkN2IyYzYzYTVhNTM4ZjU1MmQ0YWRjYjlhNGZhOTE2MTk1YzQ5NjEzZTY1NWQxGjAYBgNVBAsMEUFBQSBDZXJ0aWZp"
    "Y2F0aW9uMRMwEQYDVQQKDApBcHBsZSBJbmMuMRMwEQYDVQQIDApDYWxpZm9ybmlhMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcD"
    "QgAEQzJUSs8yPbd0RDyq8zn1bn6VxyT6wsFCWfNl4kRWULK1+yhbz1Sby2BZRBLnaCokJ+6tqftS3+0LGrF+0J+pvaOCAiYw"
    "ggIiMAwGA1UdEwEB/wQCMAAwDgYDVR0PAQH/BAQDAgTwMBQGA1UdJQQNMAsGCSqGSIb3Y2QEGDB6BgkqhkiG92NkCAUEbTBr"
    "pAMCAQq/iTADAgEAv4kxAwIBAL+JMgMCAQC/iTMDAgEAv4k0HgQcMTIzNDU2Nzg5MC5jb20uZXhhbXBsZS5teWFwcL+JNgMC"
    "AQS/iTcDAgEAv4k5AwIBAL+JOgMCAQC/iTsDAgEAqgMCAQAwgeAGCSqGSIb3Y2QIBwSB0jCBz7+KeAYEBDI3LjC/iFADAgEC"
    "v4p5CQQHMS4wLjIxNr+KewkEBzI0QTMyNWK/inwGBAQyNy4wv4p9BgQEMjcuML+KfgMCAQC/in8DAgEAv4sAAwIBAL+LAQMC"
    "AQC/iwIDAgEAv4sDAwIBAL+LBAMCAQG/iwUDAgEAv4sKEAQOMjQuMS4zMjUuMC4yLDC/iwsQBA4yNC4xLjMyNS4wLjIsML+L"
    "DBAEDjI0LjEuMzI1LjAuMiwwv4gCCgQIaXBob25lb3O/iAUKBAhJbnRlcm5hbDAzBgkqhkiG92NkCAIEJjAkoSIEIIe30G2T"
    "pClORvAR5mtsxADwurIHKZdsYZWAtCrmC/9uMFgGCSqGSIb3Y2QIBgRLMEmjRwRFMEMMAjExMD0wCgwDb2tkoQMBAf8wCQwC"
    "b2GhAwEB/zALDARvc2duoQMBAf8wCwwEb2RlbKEDAQH/MAoMA29ja6EDAQH/MAoGCCoEggFdhkjOPQQDAgNoADBlAjAhvMdo"
    "9tEpybaxrgm8NbJNfjTLP1TZvLEXFOGj4cgzQd5jAXccvIDc2uq/dYPL9R0CMQCk6jEvvN5BXTKG9qw97fX5zVli4QPERTqs"
    "OuF4VxUxFl6m9XXT6EXGAhZUxKlC7T0wIAIBBAIBAQQYZXhhbXBsZV9zZXJ2ZXJfY2hhbGxlbmdlMGACAQUCAQEEWHJia3RN"
    "cTg5bXZEcFJDSy84bGNQaGRMNGRXUXo5T1hJd0hHZGU1eFFmU3VJS3NOM09qT1dGOHUrdjBVQTRxOHZqQ1JnRUVKVGxjOUJ3"
    "aUl6TlNOT0hRPT0wDgIBBgIBAQQGQVRURVNUMBICAQcCAQEECnByb2R1Y3Rpb24wIAIBDAIBAQQYMjAyNi0wNC0yMVQxODox"
    "MzoxMi4xNTNaMCACARUCAQEEGDIwMjYtMDctMjBUMTg6MTM6MTIuMTUzWgAAAAAAAKCAMIIDrjCCA1SgAwIBAgIQZgI4gAAU"
    "Jvddiw4VLF9uQzAKBggqhkjOPQQDAjB8MTAwLgYDVQQDDCdBcHBsZSBBcHBsaWNhdGlvbiBJbnRlZ3JhdGlvbiBDQSA1IC0g"
    "RzExJjAkBgNVBAsMHUFwcGxlIENlcnRpZmljYXRpb24gQXV0aG9yaXR5MRMwEQYDVQQKDApBcHBsZSBJbmMuMQswCQYDVQQG"
    "EwJVUzAeFw0yNjAxMjAyMDIxMDlaFw0yNzAyMTgxODU4MzlaMFoxNjA0BgNVBAMMLUFwcGxpY2F0aW9uIEF0dGVzdGF0aW9u"
    "IEZyYXVkIFJlY2VpcHQgU2lnbmluZzETMBEGA1UECgwKQXBwbGUgSW5jLjELMAkGA1UEBhMCVVMwWTATBgcqhkjOPQIBBggq"
    "hkjOPQMBBwNCAAQ7GK7OxRmtilNRtEBEtKMDmVe0zb1bhR/gGm/t4o3vsPqww2oCpB9EbgBtWA5WimeAiQfzSICRQ4sgzqpM"
    "ndxWo4IB2DCCAdQwDAYDVR0TAQH/BAIwADAfBgNVHSMEGDAWgBTZF/5LZ5A4S5L0287VV4AUC489yTBDBggrBgEFBQcBAQQ3"
    "MDUwMwYIKwYBBQUHMAGGJ2h0dHA6Ly9vY3NwLmFwcGxlLmNvbS9vY3NwMDMtYWFpY2E1ZzEwMTCCARwGA1UdIASCARMwggEP"
    "MIIBCwYJKoZIhvdjZAUBMIH9MIHDBggrBgEFBQcCAjCBtgyBs1JlbGlhbmNlIG9uIHRoaXMgY2VydGlmaWNhdGUgYnkgYW55"
    "IHBhcnR5IGFzc3VtZXMgYWNjZXB0YW5jZSBvZiB0aGUgdGhlbiBhcHBsaWNhYmxlIHN0YW5kYXJkIHRlcm1zIGFuZCBjb25k"
    "aXRpb25zIG9mIHVzZSwgY2VydGlmaWNhdGUgcG9saWN5IGFuZCBjZXJ0aWZpY2F0aW9uIHByYWN0aWNlIHN0YXRlbWVudHMu"
    "MDUGCCsGAQUFBwIBFilodHRwOi8vd3d3LmFwcGxlLmNvbS9jZXJ0aWZpY2F0ZWF1dGhvcml0eTAdBgNVHQ4EFgQUNFWJcHRg"
    "DiLSumfPpVtpwiPxyigwDgYDVR0PAQH/BAQDAgeAMA8GCSqGSIb3Y2QMDwQCBQAwCgYIKoZIzj0EAwIDSAAwRQIgHGeXuYJF"
    "0dbccgS3mwI8r/h78u/4k33XIMReiuRlwusCIQD8yFmEzsmhLMKGqdSSdv3w0vYl3HX8fPiHRWl75h6qtDCCAvkwggJ/oAMC"
    "AQICEFb7g9Qr/43DN5kjtVqubr0wCgYIKoZIzj0EAwMwZzEbMBkGA1UEAwwSQXBwbGUgUm9vdCBDQSAtIEczMSYwJAYDVQQL"
    "DB1BcHBsZSBDZXJ0aWZpY2F0aW9uIEF1dGhvcml0eTETMBEGA1UECgwKQXBwbGUgSW5jLjELMAkGA1UEBhMCVVMwHhcNMTkw"
    "MzIyMTc1MzMzWhcNMzQwMzIyMDAwMDAwWjB8MTAwLgYDVQQDDCdBcHBsZSBBcHBsaWNhdGlvbiBJbnRlZ3JhdGlvbiBDQSA1"
    "IC0gRzExJjAkBgNVBAsMHUFwcGxlIENlcnRpZmljYXRpb24gQXV0aG9yaXR5MRMwEQYDVQQKDApBcHBsZSBJbmMuMQswCQYD"
    "VQQGEwJVUzBZMBMGByqGSM49AgEGCCqGSM49AwEHA0IABJLOY719hrGrKAo7HOGv+wSUgJGs9jHfpssoNW9ES+Eh5VfdEo2N"
    "uoJ8lb5J+r4zyq7NBBnxL0Ml+vS+s8uDfrqjgfcwgfQwDwYDVR0TAQH/BAUwAwEB/zAfBgNVHSMEGDAWgBS7sN6hWDOImqSK"
    "md6+veuv2sskqzBGBggrBgEFBQcBAQQ6MDgwNgYIKwYBBQUHMAGGKmh0dHA6Ly9vY3NwLmFwcGxlLmNvbS9vY3NwMDMtYXBw"
    "bGVyb290Y2FnMzA3BgNVHR8EMDAuMCygKqAohiZodHRwOi8vY3JsLmFwcGxlLmNvbS9hcHBsZXJvb3RjYWczLmNybDAdBgNV"
    "HQ4EFgQU2Rf+S2eQOEuS9NvO1VeAFAuPPckwDgYDVR0PAQH/BAQDAgEGMBAGCiqGSIb3Y2QGAgMEAgUAMAoGCCqGSM49BAMD"
    "A2gAMGUCMQCNb6afoeDk7FtOc4qSfz14U5iP9NofWB7DdUr+OKhMKoMaGqoNpmRt4bmT6NFVTO0CMGc7LLTh6DcHd8vV7Hao"
    "GjpVOz81asjF5pKw4WG+gElp5F8rqWzhEQKqzGHZOLdzSjCCAkMwggHJoAMCAQICCC3F/IjSxUuVMAoGCCqGSM49BAMDMGcx"
    "GzAZBgNVBAMMEkFwcGxlIFJvb3QgQ0EgLSBHMzEmMCQGA1UECwwdQXBwbGUgQ2VydGlmaWNhdGlvbiBBdXRob3JpdHkxEzAR"
    "BgNVBAoMCkFwcGxlIEluYy4xCzAJBgNVBAYTAlVTMB4XDTE0MDQzMDE4MTkwNloXDTM5MDQzMDE4MTkwNlowZzEbMBkGA1UE"
    "AwwSQXBwbGUgUm9vdCBDQSAtIEczMSYwJAYDVQQLDB1BcHBsZSBDZXJ0aWZpY2F0aW9uIEF1dGhvcml0eTETMBEGA1UECgwK"
    "QXBwbGUgSW5jLjELMAkGA1UEBhMCVVMwdjAQBgcqhkjOPQIBBgUrgQQAIgNiAASY6S89QHKk7ZMicoETHN0QlfHFo05x3BQW"
    "2Q7lpgUqd2R7X04407scRLV/9R+2MmJdyemEW08wTxFaAP1YWAyl9Q8sTQdHE3Xal5eXbzFc7SudeyA72LlU2V6ZpDpRCjGj"
    "QjBAMB0GA1UdDgQWBBS7sN6hWDOImqSKmd6+veuv2sskqzAPBgNVHRMBAf8EBTADAQH/MA4GA1UdDwEB/wQEAwIBBjAKBggq"
    "hkjOPQQDAwNoADBlAjEAg+nBxBZeGl00GNnt7/RsDgBGS7jfskYRxQ/95nqMoaZrzsID1Jz1k8Z0uGrfqiMVAjBtZooQytQN"
    "1E/NjUM+tIpjpTNu423aF7dkH8hTJvmIYnQ5Cxdby1GoDOgYA+eisigAADGB/TCB+gIBATCBkDB8MTAwLgYDVQQDDCdBcHBs"
    "ZSBBcHBsaWNhdGlvbiBJbnRlZ3JhdGlvbiBDQSA1IC0gRzExJjAkBgNVBAsMHUFwcGxlIENlcnRpZmljYXRpb24gQXV0aG9y"
    "aXR5MRMwEQYDVQQKDApBcHBsZSBJbmMuMQswCQYDVQQGEwJVUwIQZgI4gAAUJvddiw4VLF9uQzANBglghkgBZQMEAgEFADAK"
    "BggqhkjOPQQDAgRHMEUCIFp+GIuJm5vqJhLtDX40gGP90KJtLoPyzcLEuKHYMr9zAiEAgPafgwU16p2N6GvCC3Gj4BAb66R3"
    "8+IP+Arn3QYbD9QAAAAAAAA="
)


def _settings() -> MobileSettings:
    return MobileSettings(
        app_attest_allowed_validation_categories_json="[4]",
        app_attest_allowed_bundle_versions_json='["1"]',
        _env_file=None,
    )


def _key_material() -> tuple[ec.EllipticCurvePrivateKey, bytes, bytes]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    point = public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    key_identifier = hashlib.sha256(point).digest()
    material = _encode_verification_material(
        public_key=public_key,
        key_identifier=key_identifier,
        environment="production",
        validation_category=4,
        bundle_version="1",
        receipt=b"public-receipt-fixture",
    )
    return private_key, key_identifier, material


def _assertion(
    private_key: ec.EllipticCurvePrivateKey,
    *,
    counter: int = 1,
    category: int = 4,
    bundle_version: str = "1",
    app_id: str = _APP_ID,
    include_extensions: bool = True,
    extra_top_level: bool = False,
) -> str:
    extensions = cbor2.dumps(
        {
            "apple_bundle_version_01": bundle_version,
            "apple_validation_category_01": category.to_bytes(4, "little"),
        },
        canonical=True,
    )
    auth_data = (
        hashlib.sha256(app_id.encode("ascii")).digest()
        + b"\x00"
        + counter.to_bytes(4, "big")
        + (extensions if include_extensions else b"")
    )
    nonce = hashlib.sha256(
        auth_data + hashlib.sha256(_CLIENT_DATA.encode("ascii")).digest()
    ).digest()
    signature = private_key.sign(nonce, ec.ECDSA(hashes.SHA256()))
    payload: dict[str, object] = {
        "signature": signature,
        "authenticatorData": auth_data,
    }
    if extra_top_level:
        payload["verdict"] = "trusted"
    return base64.b64encode(cbor2.dumps(payload, canonical=True)).decode("ascii")


def test_official_apple_2026_authenticator_sample_parses_exact_extensions() -> None:
    auth_data = base64.b64decode(_APPLE_SAMPLE_AUTH_DATA, validate=True)
    certificate = x509.load_der_x509_certificate(
        base64.b64decode(_APPLE_SAMPLE_LEAF_CERTIFICATE, validate=True)
    )
    public_key = certificate.public_key()
    assert isinstance(public_key, ec.EllipticCurvePublicKey)

    category, bundle_version = _parse_attestation_auth_data(
        auth_data,
        key_identifier=base64.b64decode(_APPLE_SAMPLE_KEY_ID, validate=True),
        public_key=public_key,
        app_id=_APPLE_SAMPLE_APP_ID,
        environment="production",
        allowed_categories=frozenset({1}),
        allowed_bundle_versions=frozenset({"1"}),
    )

    assert category == 1
    assert bundle_version == "1"


@pytest.mark.asyncio
async def test_official_apple_2026_receipt_verifies_signature_path_and_bindings() -> None:
    certificate = x509.load_der_x509_certificate(
        base64.b64decode(_APPLE_SAMPLE_LEAF_CERTIFICATE, validate=True)
    )
    verifier = PyAttestAppleAppAttestVerifier(
        settings=_settings(),
        now=lambda: datetime(2026, 4, 21, 18, 13, 13, tzinfo=UTC),
    )

    await verifier._verify_receipt(
        base64.b64decode(_APPLE_SAMPLE_RECEIPT, validate=True),
        leaf_certificate=certificate,
        app_id=_APPLE_SAMPLE_APP_ID,
        server_challenge="example_server_challenge",
        environment="production",
    )


@pytest.mark.asyncio
async def test_assertion_verifies_signature_rp_id_policy_and_increasing_counter() -> None:
    private_key, key_identifier, material = _key_material()
    verifier = PyAttestAppleAppAttestVerifier(settings=_settings())

    verdict = await verifier.verify_assertion(
        assertion_object=_assertion(private_key, counter=7),
        key_id=base64.b64encode(key_identifier).decode("ascii"),
        client_data=_CLIENT_DATA,
        app_id=_APP_ID,
        verification_material=material,
        previous_counter=6,
    )

    assert verdict.counter == 7


@pytest.mark.parametrize(
    ("assertion_options", "previous_counter"),
    [
        ({"category": 3}, 0),
        ({"bundle_version": "2"}, 0),
        ({"counter": 2}, 2),
        ({"include_extensions": False}, 0),
        ({"extra_top_level": True}, 0),
        ({"app_id": "ABCDEFGHIJ.com.attacker.clone"}, 0),
    ],
)
@pytest.mark.asyncio
async def test_assertion_rejects_policy_replay_shape_and_rp_id_mismatches(
    assertion_options: dict[str, object],
    previous_counter: int,
) -> None:
    private_key, key_identifier, material = _key_material()
    verifier = PyAttestAppleAppAttestVerifier(settings=_settings())

    with pytest.raises(MobileIntegrityRejected) as caught:
        await verifier.verify_assertion(
            assertion_object=_assertion(private_key, **assertion_options),
            key_id=base64.b64encode(key_identifier).decode("ascii"),
            client_data=_CLIENT_DATA,
            app_id=_APP_ID,
            verification_material=material,
            previous_counter=previous_counter,
        )

    assert caught.value.reason == "provider_assertion"


@pytest.mark.asyncio
async def test_assertion_rejects_noncanonical_base64_and_tampered_signature() -> None:
    private_key, key_identifier, material = _key_material()
    verifier = PyAttestAppleAppAttestVerifier(settings=_settings())
    proof = _assertion(private_key)
    tampered_payload = cbor2.loads(base64.b64decode(proof, validate=True))
    signature = tampered_payload["signature"]
    tampered_payload["signature"] = bytes([signature[0] ^ 1]) + signature[1:]
    tampered_proof = base64.b64encode(
        cbor2.dumps(tampered_payload, canonical=True)
    ).decode("ascii")

    for invalid_proof in (proof + "\n", tampered_proof):
        with pytest.raises(MobileIntegrityRejected) as caught:
            await verifier.verify_assertion(
                assertion_object=invalid_proof,
                key_id=base64.b64encode(key_identifier).decode("ascii"),
                client_data=_CLIENT_DATA,
                app_id=_APP_ID,
                verification_material=material,
                previous_counter=0,
            )
        assert caught.value.reason == "provider_assertion"


@pytest.mark.asyncio
async def test_assertion_distinguishes_server_material_or_policy_unavailability() -> None:
    private_key, key_identifier, material = _key_material()
    key_id = base64.b64encode(key_identifier).decode("ascii")
    missing_policy = PyAttestAppleAppAttestVerifier(settings=MobileSettings(_env_file=None))
    with pytest.raises(MobileIntegrityUnavailable):
        await missing_policy.verify_assertion(
            assertion_object=_assertion(private_key),
            key_id=key_id,
            client_data=_CLIENT_DATA,
            app_id=_APP_ID,
            verification_material=material,
            previous_counter=0,
        )

    verifier = PyAttestAppleAppAttestVerifier(settings=_settings())
    corrupted = json.loads(material)
    corrupted["version"] = 2
    with pytest.raises(MobileIntegrityUnavailable):
        await verifier.verify_assertion(
            assertion_object=_assertion(private_key),
            key_id=key_id,
            client_data=_CLIENT_DATA,
            app_id=_APP_ID,
            verification_material=json.dumps(corrupted).encode("ascii"),
            previous_counter=0,
        )


def test_verification_material_is_fixed_bounded_and_key_bound() -> None:
    _private_key, key_identifier, material = _key_material()

    decoded = json.loads(material)
    assert set(decoded) == {
        "algorithm",
        "attested_bundle_version",
        "attested_validation_category",
        "curve",
        "environment",
        "key_binding",
        "public_key_spki",
        "receipt_digest",
        "version",
    }
    assert decoded["version"] == 1
    assert len(material) < 4_096

    other_key_identifier = b"X" * 32
    with pytest.raises(ValueError):
        _decode_verification_material(material, key_identifier=other_key_identifier)
