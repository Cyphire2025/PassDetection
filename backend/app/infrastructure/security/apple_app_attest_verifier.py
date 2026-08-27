"""Strict Apple App Attest verification built around the maintained pyattest core.

``pyattest`` owns certificate-path, nonce, key-identifier, RP-ID, initial-counter,
environment, credential, and assertion-signature cryptography. This adapter adds
the bounded wire contract, Apple receipt verification, the iOS 27 extension policy,
strict assertion replay checks, and a deterministic public verification envelope.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import io
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, TypeAlias, cast

import cbor2
from asn1crypto import cms, core
from asn1crypto import x509 as asn1_x509
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pyattest.assertion import Assertion
from pyattest.attestation import Attestation
from pyattest.configs.apple import AppleConfig
from pyattest.exceptions import PyAttestException
from pyhanko_certvalidator import CertificateValidator, ValidationContext
from pyhanko_certvalidator.errors import (
    PathBuildingError,
)
from pyhanko_certvalidator.errors import (
    ValidationError as CertificateValidationError,
)

from app.application.mobile.app_integrity import (
    AppleAppAttestAssertionVerdict,
    AppleAppAttestRegistrationVerdict,
    MobileIntegrityRejected,
    MobileIntegrityUnavailable,
)
from app.core.config.settings import MobileSettings, get_settings

_APPLE_ATTEST_FORMAT = "apple-appattest"
_APPLE_DEVELOPMENT_AAGUID = b"appattestdevelop"
_APPLE_PRODUCTION_AAGUID = b"appattest" + (b"\x00" * 7)
_APPLE_RECEIPT_ROOT_SHA256 = bytes.fromhex(
    "63343abfb89a6a03ebb57e9b3f5fa7be7c4f5c756f3017b3a8c488c3653e9179"
)
_APPLE_RECEIPT_SIGNER_EXTENSION_OID = "1.2.840.113635.100.12.15"
_APPLE_RECEIPT_SIGNER_COMMON_NAME = "Application Attestation Fraud Receipt Signing"
_APPLE_VALIDATION_CATEGORY_EXTENSION = "apple_validation_category_01"
_APPLE_BUNDLE_VERSION_EXTENSION = "apple_bundle_version_01"
_APPLE_EXTENSION_KEYS = frozenset(
    {_APPLE_VALIDATION_CATEGORY_EXTENSION, _APPLE_BUNDLE_VERSION_EXTENSION}
)
_VERIFICATION_MATERIAL_VERSION = 1
_VERIFICATION_MATERIAL_KEYS = frozenset(
    {
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
)
_BUNDLE_VERSION_PATTERN = re.compile(r"^[0-9]{1,8}(?:\.[0-9]{1,8}){0,2}$")
_BASE64URL_DIGEST_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_MAX_ATTESTATION_AUTH_DATA_BYTES = 4_096
_MAX_ASSERTION_AUTH_DATA_BYTES = 1_024
_MAX_CERTIFICATE_BYTES = 8_192
_MAX_RECEIPT_BYTES = 24_576
_MAX_SIGNATURE_BYTES = 256
_MAX_VERIFICATION_MATERIAL_BYTES = 4_096
_RECEIPT_ATTRIBUTE_TYPES = frozenset({2, 3, 4, 5, 6, 7, 12, 21})
_SAFE_CBOR_EXCEPTIONS = (
    cbor2.CBORDecodeError,
    EOFError,
    OverflowError,
    RecursionError,
    TypeError,
    UnicodeError,
    ValueError,
)

_Environment: TypeAlias = Literal["development", "production"]


class _ReceiptAttribute(core.Sequence):  # type: ignore[misc]
    _fields = [
        ("type", core.Integer),
        ("version", core.Integer),
        ("value", core.OctetString),
    ]


class _ReceiptPayload(core.SetOf):  # type: ignore[misc]
    _child_spec = _ReceiptAttribute


class PyAttestAppleAppAttestVerifier:
    """Verify Apple App Attest proofs without trusting client-provided verdicts."""

    def __init__(
        self,
        *,
        settings: MobileSettings | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings or get_settings().mobile
        self._now = now or (lambda: datetime.now(tz=UTC))

    async def verify_attestation(
        self,
        *,
        attestation_object: str,
        key_id: str,
        server_challenge: str,
        app_id: str,
        environment: _Environment,
    ) -> AppleAppAttestRegistrationVerdict:
        try:
            raw = _decode_standard_base64(
                attestation_object,
                minimum_bytes=256,
                maximum_bytes=self._settings.app_integrity_proof_max_bytes,
            )
            key_identifier = _decode_standard_base64(
                key_id,
                minimum_bytes=32,
                maximum_bytes=32,
            )
            _validate_client_data(server_challenge)
            _validate_app_id(app_id)
            policy = self._policy()
            parsed = _parse_attestation(
                raw,
                key_identifier=key_identifier,
                app_id=app_id,
                environment=environment,
                allowed_categories=policy[0],
                allowed_bundle_versions=policy[1],
            )
            await self._verify_receipt(
                parsed.receipt,
                leaf_certificate=parsed.leaf_certificate,
                app_id=app_id,
                server_challenge=server_challenge,
                environment=environment,
            )

            config = AppleConfig(
                key_id=key_identifier,
                app_id=app_id,
                production=environment == "production",
            )
            attestation = Attestation(raw, server_challenge.encode("ascii"), config)
            await attestation.verify()
            _validate_pyattest_path(attestation, config)

            public_key = parsed.leaf_certificate.public_key()
            if not isinstance(public_key, ec.EllipticCurvePublicKey):
                raise _RejectedProof
            material = _encode_verification_material(
                public_key=public_key,
                key_identifier=key_identifier,
                environment=environment,
                validation_category=parsed.validation_category,
                bundle_version=parsed.bundle_version,
                receipt=parsed.receipt,
            )
            return AppleAppAttestRegistrationVerdict(
                verification_material=material,
                counter=0,
                environment=environment,
            )
        except asyncio.CancelledError:
            raise
        except MobileIntegrityUnavailable:
            raise
        except (
            _RejectedProof,
            InvalidSignature,
            PyAttestException,
            binascii.Error,
        ) as exc:
            raise MobileIntegrityRejected("provider_attestation") from exc
        except Exception as exc:
            raise MobileIntegrityUnavailable(
                "Apple App Attest verification is unavailable"
            ) from exc

    async def verify_assertion(
        self,
        *,
        assertion_object: str,
        key_id: str,
        client_data: str,
        app_id: str,
        verification_material: bytes,
        previous_counter: int,
    ) -> AppleAppAttestAssertionVerdict:
        try:
            raw = _decode_standard_base64(
                assertion_object,
                minimum_bytes=64,
                maximum_bytes=self._settings.app_integrity_proof_max_bytes,
            )
            key_identifier = _decode_standard_base64(
                key_id,
                minimum_bytes=32,
                maximum_bytes=32,
            )
            _validate_client_data(client_data)
            _validate_app_id(app_id)
            if previous_counter < 0 or previous_counter > (1 << 63) - 1:
                raise _RejectedProof
            material = _decode_verification_material(
                verification_material,
                key_identifier=key_identifier,
            )
            policy = self._policy()
            parsed = _parse_assertion(
                raw,
                app_id=app_id,
                allowed_categories=policy[0],
                allowed_bundle_versions=policy[1],
            )
            if parsed.counter <= previous_counter or parsed.counter > (1 << 63) - 1:
                raise _RejectedProof

            config = AppleConfig(
                key_id=key_identifier,
                app_id=app_id,
                production=material.environment == "production",
            )
            assertion = Assertion(
                raw,
                hashlib.sha256(client_data.encode("ascii")).digest(),
                material.public_key,
                config,
            )
            assertion.verify()
            returned_counter = assertion.data.get("counter")
            returned_rp_id = assertion.data.get("rp_id")
            if returned_counter != parsed.counter or not isinstance(returned_rp_id, bytes):
                raise _RejectedProof
            if not hmac.compare_digest(returned_rp_id, hashlib.sha256(app_id.encode()).digest()):
                raise _RejectedProof
            return AppleAppAttestAssertionVerdict(counter=parsed.counter)
        except asyncio.CancelledError:
            raise
        except MobileIntegrityUnavailable:
            raise
        except (
            _RejectedProof,
            InvalidSignature,
            PyAttestException,
            binascii.Error,
        ) as exc:
            raise MobileIntegrityRejected("provider_assertion") from exc
        except Exception as exc:
            raise MobileIntegrityUnavailable(
                "Apple App Attest verification is unavailable"
            ) from exc

    def _policy(self) -> tuple[frozenset[int], frozenset[str]]:
        categories_json = self._settings.app_attest_allowed_validation_categories_json
        bundle_versions_json = self._settings.app_attest_allowed_bundle_versions_json
        if categories_json is None or bundle_versions_json is None:
            raise MobileIntegrityUnavailable("Apple App Attest policy is not configured")
        categories: object = json.loads(categories_json)
        bundle_versions: object = json.loads(bundle_versions_json)
        if not isinstance(categories, list) or not isinstance(bundle_versions, list):
            raise MobileIntegrityUnavailable("Apple App Attest policy is invalid")
        return (
            frozenset(cast(list[int], categories)),
            frozenset(cast(list[str], bundle_versions)),
        )

    async def _verify_receipt(
        self,
        receipt: bytes,
        *,
        leaf_certificate: x509.Certificate,
        app_id: str,
        server_challenge: str,
        environment: _Environment,
    ) -> None:
        now = self._validated_now()
        parsed = _parse_receipt(
            receipt,
            leaf_certificate=leaf_certificate,
            app_id=app_id,
            server_challenge=server_challenge,
            environment=environment,
            now=now,
            maximum_age_seconds=max(
                300,
                self._settings.app_integrity_challenge_ttl_seconds + 60,
            ),
        )
        context = ValidationContext(
            trust_roots=[parsed.root_certificate],
            allow_fetching=False,
            revocation_mode="soft-fail",
            moment=now,
        )
        validator = CertificateValidator(
            parsed.signer_certificate,
            parsed.intermediate_certificates,
            validation_context=context,
        )
        try:
            await validator.async_validate_usage({"digital_signature"})  # type: ignore[no-untyped-call]
        except (CertificateValidationError, PathBuildingError) as exc:
            raise _RejectedProof from exc

    def _validated_now(self) -> datetime:
        now = self._now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise MobileIntegrityUnavailable("Apple App Attest clock is unavailable")
        return now.astimezone(UTC)


class _RejectedProof(ValueError):
    """A generic internal marker that never exposes parser details to clients."""


class _ParsedAttestation:
    __slots__ = (
        "bundle_version",
        "leaf_certificate",
        "receipt",
        "validation_category",
    )

    def __init__(
        self,
        *,
        leaf_certificate: x509.Certificate,
        receipt: bytes,
        validation_category: int,
        bundle_version: str,
    ) -> None:
        self.leaf_certificate = leaf_certificate
        self.receipt = receipt
        self.validation_category = validation_category
        self.bundle_version = bundle_version


class _ParsedAssertion:
    __slots__ = ("counter",)

    def __init__(self, *, counter: int) -> None:
        self.counter = counter


class _VerificationMaterial:
    __slots__ = ("environment", "public_key")

    def __init__(
        self,
        *,
        environment: _Environment,
        public_key: ec.EllipticCurvePublicKey,
    ) -> None:
        self.environment = environment
        self.public_key = public_key


class _ParsedReceipt:
    __slots__ = (
        "intermediate_certificates",
        "root_certificate",
        "signer_certificate",
    )

    def __init__(
        self,
        *,
        signer_certificate: asn1_x509.Certificate,
        intermediate_certificates: list[asn1_x509.Certificate],
        root_certificate: asn1_x509.Certificate,
    ) -> None:
        self.signer_certificate = signer_certificate
        self.intermediate_certificates = intermediate_certificates
        self.root_certificate = root_certificate


def _parse_attestation(
    raw: bytes,
    *,
    key_identifier: bytes,
    app_id: str,
    environment: _Environment,
    allowed_categories: frozenset[int],
    allowed_bundle_versions: frozenset[str],
) -> _ParsedAttestation:
    decoded = _decode_cbor_exact(raw)
    if not isinstance(decoded, dict) or set(decoded) != {"fmt", "attStmt", "authData"}:
        raise _RejectedProof
    if decoded["fmt"] != _APPLE_ATTEST_FORMAT:
        raise _RejectedProof
    statement = decoded["attStmt"]
    auth_data = decoded["authData"]
    if not isinstance(statement, dict) or set(statement) != {"x5c", "receipt"}:
        raise _RejectedProof
    chain = statement["x5c"]
    receipt = statement["receipt"]
    if not isinstance(chain, list) or len(chain) != 2:
        raise _RejectedProof
    if any(
        not isinstance(item, bytes) or not 256 <= len(item) <= _MAX_CERTIFICATE_BYTES
        for item in chain
    ):
        raise _RejectedProof
    if not isinstance(receipt, bytes) or not 256 <= len(receipt) <= _MAX_RECEIPT_BYTES:
        raise _RejectedProof
    if (
        not isinstance(auth_data, bytes)
        or not 164 <= len(auth_data) <= _MAX_ATTESTATION_AUTH_DATA_BYTES
    ):
        raise _RejectedProof
    try:
        leaf_certificate = x509.load_der_x509_certificate(chain[0])
        x509.load_der_x509_certificate(chain[1])
    except ValueError as exc:
        raise _RejectedProof from exc
    public_key = leaf_certificate.public_key()
    if not isinstance(public_key, ec.EllipticCurvePublicKey) or not isinstance(
        public_key.curve,
        ec.SECP256R1,
    ):
        raise _RejectedProof

    category, bundle_version = _parse_attestation_auth_data(
        auth_data,
        key_identifier=key_identifier,
        public_key=public_key,
        app_id=app_id,
        environment=environment,
        allowed_categories=allowed_categories,
        allowed_bundle_versions=allowed_bundle_versions,
    )
    return _ParsedAttestation(
        leaf_certificate=leaf_certificate,
        receipt=receipt,
        validation_category=category,
        bundle_version=bundle_version,
    )


def _parse_attestation_auth_data(
    auth_data: bytes,
    *,
    key_identifier: bytes,
    public_key: ec.EllipticCurvePublicKey,
    app_id: str,
    environment: _Environment,
    allowed_categories: frozenset[int],
    allowed_bundle_versions: frozenset[str],
) -> tuple[int, str]:
    rp_id = auth_data[:32]
    flags = auth_data[32]
    counter = int.from_bytes(auth_data[33:37], "big")
    if not hmac.compare_digest(rp_id, hashlib.sha256(app_id.encode("ascii")).digest()):
        raise _RejectedProof
    if flags & 0x22 or not flags & 0x40 or counter != 0:
        raise _RejectedProof

    credential_data = auth_data[37:]
    aaguid = credential_data[:16]
    expected_aaguid = (
        _APPLE_PRODUCTION_AAGUID if environment == "production" else _APPLE_DEVELOPMENT_AAGUID
    )
    if not hmac.compare_digest(aaguid, expected_aaguid):
        raise _RejectedProof
    credential_length = int.from_bytes(credential_data[16:18], "big")
    if credential_length != 32 or len(credential_data) < 18 + credential_length:
        raise _RejectedProof
    credential_id = credential_data[18 : 18 + credential_length]
    if not hmac.compare_digest(credential_id, key_identifier):
        raise _RejectedProof

    point = public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    if not hmac.compare_digest(hashlib.sha256(point).digest(), key_identifier):
        raise _RejectedProof

    cose_and_extensions = credential_data[18 + credential_length :]
    cose_key, consumed = _decode_cbor_prefix(cose_and_extensions)
    _validate_cose_key(cose_key, public_key=public_key)
    extension_bytes = cose_and_extensions[consumed:]
    category, bundle_version = _parse_extensions(extension_bytes)
    _enforce_extension_policy(
        category,
        bundle_version,
        allowed_categories=allowed_categories,
        allowed_bundle_versions=allowed_bundle_versions,
    )
    return category, bundle_version


def _parse_assertion(
    raw: bytes,
    *,
    app_id: str,
    allowed_categories: frozenset[int],
    allowed_bundle_versions: frozenset[str],
) -> _ParsedAssertion:
    decoded = _decode_cbor_exact(raw)
    if not isinstance(decoded, dict) or set(decoded) != {"signature", "authenticatorData"}:
        raise _RejectedProof
    signature = decoded["signature"]
    auth_data = decoded["authenticatorData"]
    if not isinstance(signature, bytes) or not 64 <= len(signature) <= _MAX_SIGNATURE_BYTES:
        raise _RejectedProof
    if (
        not isinstance(auth_data, bytes)
        or not 38 <= len(auth_data) <= _MAX_ASSERTION_AUTH_DATA_BYTES
    ):
        raise _RejectedProof
    if not hmac.compare_digest(
        auth_data[:32],
        hashlib.sha256(app_id.encode("ascii")).digest(),
    ):
        raise _RejectedProof
    flags = auth_data[32]
    if flags & 0x22 or flags & 0x40:
        raise _RejectedProof
    counter = int.from_bytes(auth_data[33:37], "big")
    category, bundle_version = _parse_extensions(auth_data[37:])
    _enforce_extension_policy(
        category,
        bundle_version,
        allowed_categories=allowed_categories,
        allowed_bundle_versions=allowed_bundle_versions,
    )
    return _ParsedAssertion(counter=counter)


def _parse_extensions(raw: bytes) -> tuple[int, str]:
    decoded = _decode_cbor_exact(raw)
    if not isinstance(decoded, dict) or set(decoded) != _APPLE_EXTENSION_KEYS:
        raise _RejectedProof
    raw_category = decoded[_APPLE_VALIDATION_CATEGORY_EXTENSION]
    bundle_version = decoded[_APPLE_BUNDLE_VERSION_EXTENSION]
    if not isinstance(raw_category, bytes) or len(raw_category) != 4:
        raise _RejectedProof
    category = int.from_bytes(raw_category, "little")
    if (
        not isinstance(bundle_version, str)
        or _BUNDLE_VERSION_PATTERN.fullmatch(bundle_version) is None
    ):
        raise _RejectedProof
    return category, bundle_version


def _enforce_extension_policy(
    category: int,
    bundle_version: str,
    *,
    allowed_categories: frozenset[int],
    allowed_bundle_versions: frozenset[str],
) -> None:
    if category not in allowed_categories or bundle_version not in allowed_bundle_versions:
        raise _RejectedProof


def _validate_cose_key(
    cose_key: object,
    *,
    public_key: ec.EllipticCurvePublicKey,
) -> None:
    if not isinstance(cose_key, dict) or set(cose_key) != {1, 3, -1, -2, -3}:
        raise _RejectedProof
    if cose_key[1] != 2 or cose_key[3] != -7 or cose_key[-1] != 1:
        raise _RejectedProof
    x_coordinate = cose_key[-2]
    y_coordinate = cose_key[-3]
    if (
        not isinstance(x_coordinate, bytes)
        or len(x_coordinate) != 32
        or not isinstance(y_coordinate, bytes)
        or len(y_coordinate) != 32
    ):
        raise _RejectedProof
    expected_point = public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    if not hmac.compare_digest(b"\x04" + x_coordinate + y_coordinate, expected_point):
        raise _RejectedProof


def _parse_receipt(
    receipt: bytes,
    *,
    leaf_certificate: x509.Certificate,
    app_id: str,
    server_challenge: str,
    environment: _Environment,
    now: datetime,
    maximum_age_seconds: int,
) -> _ParsedReceipt:
    try:
        content_info = cms.ContentInfo.load(receipt, strict=True)
        if content_info["content_type"].native != "signed_data":
            raise _RejectedProof
        signed_data = content_info["content"]
        if signed_data["version"].native != "v1":
            raise _RejectedProof
        digest_algorithms = {item["algorithm"].native for item in signed_data["digest_algorithms"]}
        if digest_algorithms != {"sha256"}:
            raise _RejectedProof
        encapsulated = signed_data["encap_content_info"]
        if encapsulated["content_type"].native != "data":
            raise _RejectedProof
        content = encapsulated["content"].native
        if not isinstance(content, bytes) or not 64 <= len(content) <= 8_192:
            raise _RejectedProof
        certificates = [choice.chosen for choice in signed_data["certificates"]]
        signer_infos = signed_data["signer_infos"]
        if not 2 <= len(certificates) <= 4 or len(signer_infos) != 1:
            raise _RejectedProof
        signer_info = signer_infos[0]
        if (
            signer_info["version"].native != "v1"
            or signer_info["digest_algorithm"]["algorithm"].native != "sha256"
            or signer_info["signature_algorithm"]["algorithm"].native != "sha256_ecdsa"
            or signer_info["sid"].name != "issuer_and_serial_number"
            or signer_info["signed_attrs"].native is not None
        ):
            raise _RejectedProof
        signer = _find_receipt_signer(certificates, signer_info)
        root = _find_receipt_root(certificates)
        _validate_receipt_signer_identity(signer)
        excluded_certificates = {signer.dump(), root.dump()}
        intermediates = [
            certificate
            for certificate in certificates
            if certificate.dump() not in excluded_certificates
        ]
        cryptography_signer = x509.load_der_x509_certificate(signer.dump())
        signer_public_key = cryptography_signer.public_key()
        if not isinstance(signer_public_key, ec.EllipticCurvePublicKey):
            raise _RejectedProof
        signer_public_key.verify(
            signer_info["signature"].native,
            content,
            ec.ECDSA(hashes.SHA256()),
        )
        _validate_receipt_payload(
            content,
            leaf_certificate=leaf_certificate,
            app_id=app_id,
            server_challenge=server_challenge,
            environment=environment,
            now=now,
            maximum_age_seconds=maximum_age_seconds,
        )
    except _RejectedProof:
        raise
    except (InvalidSignature, OverflowError, TypeError, ValueError) as exc:
        raise _RejectedProof from exc
    return _ParsedReceipt(
        signer_certificate=signer,
        intermediate_certificates=intermediates,
        root_certificate=root,
    )


def _find_receipt_signer(
    certificates: list[asn1_x509.Certificate],
    signer_info: cms.SignerInfo,
) -> asn1_x509.Certificate:
    signer_id = signer_info["sid"].chosen
    matches = [
        certificate
        for certificate in certificates
        if certificate.serial_number == signer_id["serial_number"].native
        and certificate.issuer.dump() == signer_id["issuer"].dump()
    ]
    if len(matches) != 1:
        raise _RejectedProof
    return matches[0]


def _find_receipt_root(
    certificates: list[asn1_x509.Certificate],
) -> asn1_x509.Certificate:
    matches = [
        certificate
        for certificate in certificates
        if hmac.compare_digest(
            hashlib.sha256(certificate.dump()).digest(),
            _APPLE_RECEIPT_ROOT_SHA256,
        )
    ]
    if not matches:
        root_path = Path(__file__).with_name("certificates") / "apple_root_ca_g3.pem"
        root = x509.load_pem_x509_certificate(root_path.read_bytes())
        if not hmac.compare_digest(root.fingerprint(hashes.SHA256()), _APPLE_RECEIPT_ROOT_SHA256):
            raise MobileIntegrityUnavailable("Apple receipt trust anchor is invalid")
        return asn1_x509.Certificate.load(
            root.public_bytes(serialization.Encoding.DER),
            strict=True,
        )
    if len(matches) != 1:
        raise _RejectedProof
    return matches[0]


def _validate_receipt_signer_identity(certificate: asn1_x509.Certificate) -> None:
    subject = certificate.subject.native
    if (
        subject.get("common_name") != _APPLE_RECEIPT_SIGNER_COMMON_NAME
        or subject.get("organization_name") != "Apple Inc."
        or subject.get("country_name") != "US"
    ):
        raise _RejectedProof
    matching_extensions = [
        extension
        for extension in certificate["tbs_certificate"]["extensions"]
        if extension["extn_id"].dotted == _APPLE_RECEIPT_SIGNER_EXTENSION_OID
    ]
    if len(matching_extensions) != 1:
        raise _RejectedProof


def _validate_receipt_payload(
    content: bytes,
    *,
    leaf_certificate: x509.Certificate,
    app_id: str,
    server_challenge: str,
    environment: _Environment,
    now: datetime,
    maximum_age_seconds: int,
) -> None:
    payload = _ReceiptPayload.load(content, strict=True)
    attributes: dict[int, bytes] = {}
    for attribute in payload:
        attribute_type = attribute["type"].native
        version = attribute["version"].native
        value = attribute["value"].native
        if (
            isinstance(attribute_type, bool)
            or not isinstance(attribute_type, int)
            or version != 1
            or not isinstance(value, bytes)
            or attribute_type in attributes
        ):
            raise _RejectedProof
        attributes[attribute_type] = value
    if set(attributes) != _RECEIPT_ATTRIBUTE_TYPES:
        raise _RejectedProof
    if not hmac.compare_digest(attributes[2], app_id.encode("ascii")):
        raise _RejectedProof
    if not hmac.compare_digest(
        attributes[3],
        leaf_certificate.public_bytes(serialization.Encoding.DER),
    ):
        raise _RejectedProof
    if not hmac.compare_digest(attributes[4], server_challenge.encode("ascii")):
        raise _RejectedProof
    _decode_standard_base64(
        attributes[5].decode("ascii"),
        minimum_bytes=64,
        maximum_bytes=64,
    )
    if attributes[6] != b"ATTEST" or attributes[7] != environment.encode("ascii"):
        raise _RejectedProof
    created_at = _parse_receipt_time(attributes[12])
    expires_at = _parse_receipt_time(attributes[21])
    if (
        created_at > now + timedelta(seconds=30)
        or now - created_at > timedelta(seconds=maximum_age_seconds)
        or expires_at <= now
        or expires_at <= created_at
    ):
        raise _RejectedProof


def _parse_receipt_time(raw: bytes) -> datetime:
    try:
        encoded = raw.decode("ascii")
        parsed = datetime.fromisoformat(encoded.replace("Z", "+00:00"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise _RejectedProof from exc
    if not encoded.endswith("Z") or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _RejectedProof
    return parsed.astimezone(UTC)


def _encode_verification_material(
    *,
    public_key: ec.EllipticCurvePublicKey,
    key_identifier: bytes,
    environment: _Environment,
    validation_category: int,
    bundle_version: str,
    receipt: bytes,
) -> bytes:
    spki = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    payload = {
        "algorithm": "ES256",
        "attested_bundle_version": bundle_version,
        "attested_validation_category": validation_category,
        "curve": "P-256",
        "environment": environment,
        "key_binding": _base64url(hashlib.sha256(key_identifier).digest()),
        "public_key_spki": base64.b64encode(spki).decode("ascii"),
        "receipt_digest": _base64url(hashlib.sha256(receipt).digest()),
        "version": _VERIFICATION_MATERIAL_VERSION,
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("ascii")
    if not 32 <= len(encoded) <= _MAX_VERIFICATION_MATERIAL_BYTES:
        raise MobileIntegrityUnavailable("Apple verification material is invalid")
    return encoded


def _decode_verification_material(
    encoded: bytes,
    *,
    key_identifier: bytes,
) -> _VerificationMaterial:
    if not 32 <= len(encoded) <= _MAX_VERIFICATION_MATERIAL_BYTES:
        raise MobileIntegrityUnavailable("Apple verification material is invalid")
    try:
        payload: object = json.loads(encoded.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MobileIntegrityUnavailable("Apple verification material is invalid") from exc
    if not isinstance(payload, dict) or set(payload) != _VERIFICATION_MATERIAL_KEYS:
        raise MobileIntegrityUnavailable("Apple verification material is invalid")
    if (
        payload["version"] != _VERIFICATION_MATERIAL_VERSION
        or payload["algorithm"] != "ES256"
        or payload["curve"] != "P-256"
        or payload["environment"] not in {"development", "production"}
        or isinstance(payload["attested_validation_category"], bool)
        or not isinstance(payload["attested_validation_category"], int)
        or not isinstance(payload["attested_bundle_version"], str)
        or _BUNDLE_VERSION_PATTERN.fullmatch(payload["attested_bundle_version"]) is None
        or not isinstance(payload["key_binding"], str)
        or _BASE64URL_DIGEST_PATTERN.fullmatch(payload["key_binding"]) is None
        or not isinstance(payload["receipt_digest"], str)
        or _BASE64URL_DIGEST_PATTERN.fullmatch(payload["receipt_digest"]) is None
        or not isinstance(payload["public_key_spki"], str)
    ):
        raise MobileIntegrityUnavailable("Apple verification material is invalid")
    expected_binding = _base64url(hashlib.sha256(key_identifier).digest())
    if not hmac.compare_digest(payload["key_binding"], expected_binding):
        raise _RejectedProof
    try:
        spki = _decode_standard_base64(
            payload["public_key_spki"],
            minimum_bytes=64,
            maximum_bytes=256,
        )
        public_key = serialization.load_der_public_key(spki)
    except (TypeError, ValueError, binascii.Error) as exc:
        raise MobileIntegrityUnavailable("Apple verification material is invalid") from exc
    if not isinstance(public_key, ec.EllipticCurvePublicKey) or not isinstance(
        public_key.curve,
        ec.SECP256R1,
    ):
        raise MobileIntegrityUnavailable("Apple verification material is invalid")
    point = public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    if not hmac.compare_digest(hashlib.sha256(point).digest(), key_identifier):
        raise _RejectedProof
    return _VerificationMaterial(
        environment=cast(_Environment, payload["environment"]),
        public_key=public_key,
    )


def _validate_pyattest_path(attestation: Attestation, config: AppleConfig) -> None:
    data = attestation.data
    if not isinstance(data, Mapping) or set(data) != {"data", "certs"}:
        raise _RejectedProof
    path = data["certs"]
    try:
        first = path.first
        last = path.last
    except AttributeError as exc:
        raise _RejectedProof from exc
    if not isinstance(first, asn1_x509.Certificate) or not isinstance(
        last,
        asn1_x509.Certificate,
    ):
        raise _RejectedProof
    if not hmac.compare_digest(
        hashlib.sha256(first.dump()).digest(),
        hashlib.sha256(config.root_ca.dump()).digest(),
    ):
        raise _RejectedProof


def _decode_standard_base64(
    encoded: str,
    *,
    minimum_bytes: int,
    maximum_bytes: int,
) -> bytes:
    if (
        not isinstance(encoded, str)
        or not encoded
        or len(encoded) % 4 != 0
        or len(encoded) > ((maximum_bytes + 2) // 3) * 4
        or not encoded.isascii()
    ):
        raise _RejectedProof
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _RejectedProof from exc
    if not minimum_bytes <= len(decoded) <= maximum_bytes or not hmac.compare_digest(
        base64.b64encode(decoded).decode("ascii"), encoded
    ):
        raise _RejectedProof
    return decoded


def _decode_cbor_exact(raw: bytes) -> object:
    value, consumed = _decode_cbor_prefix(raw)
    if consumed != len(raw):
        raise _RejectedProof
    return value


def _decode_cbor_prefix(raw: bytes) -> tuple[object, int]:
    if not raw:
        raise _RejectedProof
    stream = io.BytesIO(raw)
    try:
        value = cbor2.CBORDecoder(stream).decode()
    except _SAFE_CBOR_EXCEPTIONS as exc:
        raise _RejectedProof from exc
    return value, stream.tell()


def _validate_client_data(value: str) -> None:
    if (
        not isinstance(value, str)
        or not 16 <= len(value) <= 512
        or not value.isascii()
        or any(character.isspace() for character in value)
    ):
        raise _RejectedProof


def _validate_app_id(value: str) -> None:
    if (
        not isinstance(value, str)
        or not 14 <= len(value) <= 300
        or re.fullmatch(r"[A-Z0-9]{10}\.[A-Za-z0-9]+(?:[.-][A-Za-z0-9_-]+)+", value) is None
    ):
        raise _RejectedProof


def _base64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


__all__ = ["PyAttestAppleAppAttestVerifier"]
