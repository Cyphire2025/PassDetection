"""PII-free offline evidence for coordinator attendance QR admission.

The mobile coordinator projection receives only a SHA-256 digest of a
high-entropy opaque QR value.  Raw bearer values remain confined to the
passenger QR response and the short-lived durable attendance action that must
later be canonically validated by the server.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

AttendanceQrState = Literal["active", "missing", "inactive", "revoked", "expired"]

ATTENDANCE_QR_EVIDENCE_TTL = timedelta(hours=24)
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class AttendanceQrEvidence:
    """One bounded server observation of the latest passenger QR state."""

    token_hash: str | None
    token_version: int | None
    state: AttendanceQrState
    token_expires_at: datetime | None
    token_updated_at: datetime | None
    evidence_observed_at: datetime
    evidence_valid_until: datetime


def _utc_or_none(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(UTC)


def attendance_qr_evidence_epoch(observed_at: datetime | None = None) -> int:
    """Return the UTC lease bucket that forces periodic online renewal."""

    observed = observed_at or datetime.now(tz=UTC)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("Attendance QR evidence requires a timezone-aware observation.")
    return int(observed.astimezone(UTC).timestamp() // ATTENDANCE_QR_EVIDENCE_TTL.total_seconds())


def build_attendance_qr_evidence(
    *,
    token_hash: str | None,
    token_version: int | None,
    is_active: bool | None,
    revoked_at: datetime | None,
    expires_at: datetime | None,
    updated_at: datetime | None,
    observed_at: datetime | None = None,
) -> AttendanceQrEvidence:
    """Normalize mutable token state without ever returning an inactive hash."""

    observed_source = observed_at or datetime.now(tz=UTC)
    if observed_source.tzinfo is None or observed_source.utcoffset() is None:
        raise ValueError("Attendance QR evidence requires a timezone-aware observation.")
    observed = observed_source.astimezone(UTC)
    normalized_hash = token_hash.casefold() if isinstance(token_hash, str) else None
    normalized_expires_at = _utc_or_none(expires_at)
    normalized_updated_at = _utc_or_none(updated_at)

    if token_version is None:
        state: AttendanceQrState = "missing"
    elif token_version < 1:
        state = "inactive"
    elif revoked_at is not None:
        state = "revoked"
    elif normalized_expires_at is None or normalized_expires_at <= observed:
        state = "expired"
    elif not is_active:
        state = "inactive"
    elif (
        normalized_updated_at is None
        or normalized_updated_at > observed
        or normalized_hash is None
        or _SHA256_HEX.fullmatch(normalized_hash) is None
    ):
        # A malformed legacy/database row is not usable offline.  Treating it
        # as inactive avoids exposing malformed lookup material to a device.
        state = "inactive"
    else:
        state = "active"

    active_hash = normalized_hash if state == "active" else None
    evidence_valid_until = observed
    if state == "active" and normalized_expires_at is not None:
        evidence_valid_until = min(
            normalized_expires_at,
            observed + ATTENDANCE_QR_EVIDENCE_TTL,
        )

    return AttendanceQrEvidence(
        token_hash=active_hash,
        token_version=token_version,
        state=state,
        token_expires_at=normalized_expires_at,
        token_updated_at=normalized_updated_at,
        evidence_observed_at=observed,
        evidence_valid_until=evidence_valid_until,
    )


__all__ = [
    "ATTENDANCE_QR_EVIDENCE_TTL",
    "AttendanceQrEvidence",
    "AttendanceQrState",
    "attendance_qr_evidence_epoch",
    "build_attendance_qr_evidence",
]
