"""Signed, bounded audit checkpoints containing no event bodies or actor PII."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import asdict
from datetime import UTC, datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.application.interfaces.audit_integrity_sink import AuditIntegrityCheckpoint


class AuditIntegrityError(RuntimeError):
    """A verification failure; caller must emit a nonzero operational result."""


def key_id(key: Ed25519PublicKey) -> str:
    return hashlib.sha256(key.public_bytes(Encoding.Raw, PublicFormat.Raw)).hexdigest()[:24]


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def encode(checkpoint: AuditIntegrityCheckpoint, key: Ed25519PrivateKey) -> bytes:
    payload = asdict(checkpoint)
    payload["observed_at"] = checkpoint.observed_at.astimezone(UTC).isoformat()
    envelope = {"checkpoint": payload, "algorithm": "Ed25519", "key_id": key_id(key.public_key())}
    return canonical({**envelope, "signature": base64.b64encode(key.sign(canonical(envelope))).decode("ascii")})


def decode(raw: bytes, keys: dict[str, Ed25519PublicKey]) -> AuditIntegrityCheckpoint:
    try:
        if len(raw) > 4096:
            raise ValueError("oversized")
        envelope = json.loads(raw)
        if set(envelope) != {"checkpoint", "algorithm", "key_id", "signature"} or envelope["algorithm"] != "Ed25519":
            raise ValueError("envelope")
        signature = base64.b64decode(envelope.pop("signature"), validate=True)
        keys[envelope["key_id"]].verify(signature, canonical(envelope))
        value = envelope["checkpoint"]
        if set(value) != {"scope_key", "integrity_version", "last_sequence", "last_hash", "observed_at"}:
            raise ValueError("fields")
        checkpoint = AuditIntegrityCheckpoint(**{**value, "observed_at": datetime.fromisoformat(value["observed_at"])})
        validate(checkpoint)
        return checkpoint
    except (ValueError, TypeError, KeyError, InvalidSignature, AttributeError) as exc:
        raise AuditIntegrityError("checkpoint_signature_or_shape_invalid") from exc


def validate(value: AuditIntegrityCheckpoint) -> None:
    if (not re.fullmatch(r"global|agency:[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", value.scope_key)
            or type(value.integrity_version) is not int or value.integrity_version != 1
            or type(value.last_sequence) is not int or value.last_sequence < 1
            or not re.fullmatch(r"[0-9a-f]{64}", value.last_hash)
            or value.observed_at.tzinfo is None or value.observed_at.utcoffset() is None):
        raise AuditIntegrityError("checkpoint_shape_invalid")


def object_key(checkpoint: AuditIntegrityCheckpoint) -> str:
    validate(checkpoint)
    return f"audit-checkpoints/v1/{checkpoint.scope_key}/{checkpoint.last_sequence:020d}.json"
