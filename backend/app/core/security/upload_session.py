"""Validation helpers for opaque public-upload session identifiers."""

from __future__ import annotations

import hmac
import re

_UPLOAD_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_UPLOAD_CREDENTIAL_RE = re.compile(r"^[A-Za-z0-9._:-]{32,128}$")


def is_valid_upload_session_id(value: str) -> bool:
    """Return whether a caller-supplied session id is bounded and log-safe."""

    return _UPLOAD_SESSION_ID_RE.fullmatch(value) is not None


def is_valid_upload_credential(value: str) -> bool:
    """Return whether an upload recovery capability has adequate entropy space."""

    return _UPLOAD_CREDENTIAL_RE.fullmatch(value) is not None


def upload_session_matches_identifier(
    session_id: str,
    expected_identifier: str,
) -> bool:
    """Bind an upload capability to the durable secret stored for the attempt."""

    return (
        is_valid_upload_credential(session_id)
        and is_valid_upload_credential(expected_identifier)
        and hmac.compare_digest(
            session_id,
            expected_identifier,
        )
    )
