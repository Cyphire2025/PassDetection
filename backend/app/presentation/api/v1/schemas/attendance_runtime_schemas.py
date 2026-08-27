"""Strict privacy-bounded attendance runtime and discard contracts."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class AttendanceRuntimeRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_kind: Literal["pwa", "webview"] = "pwa"


class AttendanceRuntimeRegistrationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_id: uuid.UUID
    runtime_kind: Literal["pwa", "webview"]
    expires_at: datetime


class AttendanceRuntimeDispositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coordinator_user_id: uuid.UUID
    status: Literal["lost", "revoked"]
    reason: str = Field(min_length=10, max_length=80)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 10:
            raise ValueError("Runtime disposition reason must contain at least 10 characters")
        return normalized


class AttendanceRuntimeDispositionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_id: uuid.UUID
    status: Literal["lost", "revoked"]
    revoked_at: datetime


class BrowserOfflineAuthorizedSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    label: str = Field(min_length=1, max_length=160)
    scheduled_starts_at: datetime
    scheduled_ends_at: datetime
    status: Literal["active"] = "active"


class BrowserOfflineAuthorizedPassenger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    label: str = Field(min_length=1, max_length=255)
    token_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    token_valid_until: datetime
    token_version: int = Field(ge=1)


class BrowserOfflineAuthorizationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coordinator_user_id: uuid.UUID
    expires_at: datetime
    group_id: uuid.UUID
    group_label: str = Field(min_length=1, max_length=160)
    issued_at: datetime
    key_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    max_suspension_seconds: int = Field(ge=60, le=604_800)
    not_before: datetime
    passengers: list[BrowserOfflineAuthorizedPassenger] = Field(max_length=2_000)
    roster_revision: int = Field(ge=0, le=(1 << 53) - 1)
    schema_version: Literal[1] = 1
    server_time: datetime
    sessions: list[BrowserOfflineAuthorizedSession] = Field(min_length=1, max_length=200)
    tenant_id: uuid.UUID


class BrowserOfflineAuthorizationBundleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    payload: str = Field(min_length=1, max_length=2_796_220, pattern=r"^[A-Za-z0-9_-]+$")
    public_key: str = Field(min_length=43, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    signature: str = Field(min_length=86, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    version: Literal["pwa-offline-authorization-v1"] = "pwa-offline-authorization-v1"


class AttendanceDiscardItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discard_event_id: uuid.UUID
    group_id: uuid.UUID
    session_id: uuid.UUID
    # Rolling clients send their pre-registration device hint. The backend
    # never authorizes from this value; the HttpOnly runtime cookie wins.
    installation_runtime_id: str | None = Field(default=None, min_length=1, max_length=128)
    scan_reference: str = Field(min_length=64, max_length=71)
    reason_category: Literal[
        "operator_discard",
        "coordinator_confirmed_rescan",
        "wrong_group",
        "expired_authorization",
        "activity_closed",
        "duplicate",
        "duplicate_local_evidence",
        "passenger_not_attending",
        "privacy_or_data_error",
        "server_rejected",
        "server_terminal_rejection",
        "corrupted_entry",
        "other",
    ]
    captured_at: datetime | None = None
    discarded_at: datetime

    @field_validator("scan_reference")
    @classmethod
    def validate_scan_reference(cls, value: str) -> str:
        normalized = value.removeprefix("sha256:")
        if _SHA256_HEX.fullmatch(normalized) is None:
            raise ValueError("Scan reference must be a lowercase SHA-256 value")
        return normalized

    @field_validator("captured_at", "discarded_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Attendance discard timestamps must include a timezone")
        return value


class AttendanceDiscardBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_id: uuid.UUID | None = None
    items: list[AttendanceDiscardItemRequest] = Field(min_length=1, max_length=100)

    @field_validator("items")
    @classmethod
    def require_unique_event_ids(
        cls,
        value: list[AttendanceDiscardItemRequest],
    ) -> list[AttendanceDiscardItemRequest]:
        event_ids = [item.discard_event_id for item in value]
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("Discard event ids must be unique within a batch")
        return value


class AttendanceDiscardItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discard_event_id: uuid.UUID
    status: Literal["accepted", "already_applied", "rejected"]
    received_at: datetime | None = None
    reason_code: str | None = Field(default=None, max_length=80)


class AttendanceDiscardBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AttendanceDiscardItemResponse]


class MobileAttendanceDiscardItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discard_event_id: uuid.UUID
    scan_reference: str = Field(min_length=64, max_length=71)
    reason_category: Literal[
        "operator_discard",
        "wrong_group",
        "expired_authorization",
        "activity_closed",
        "duplicate",
        "server_rejected",
        "corrupted_entry",
        "other",
    ]
    captured_at: datetime | None = None
    discarded_at: datetime

    @field_validator("scan_reference")
    @classmethod
    def validate_scan_reference(cls, value: str) -> str:
        normalized = value.removeprefix("sha256:")
        if _SHA256_HEX.fullmatch(normalized) is None:
            raise ValueError("Scan reference must be a lowercase SHA-256 value")
        return normalized

    @field_validator("captured_at", "discarded_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Attendance discard timestamps must include a timezone")
        return value


class MobileAttendanceDiscardBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[MobileAttendanceDiscardItemRequest] = Field(min_length=1, max_length=100)

    @field_validator("items")
    @classmethod
    def require_unique_event_ids(
        cls,
        value: list[MobileAttendanceDiscardItemRequest],
    ) -> list[MobileAttendanceDiscardItemRequest]:
        if len({item.discard_event_id for item in value}) != len(value):
            raise ValueError("Discard event ids must be unique within a batch")
        return value


__all__ = [
    "AttendanceDiscardBatchRequest",
    "AttendanceDiscardBatchResponse",
    "AttendanceDiscardItemRequest",
    "AttendanceDiscardItemResponse",
    "AttendanceRuntimeRegistrationRequest",
    "AttendanceRuntimeRegistrationResponse",
    "AttendanceRuntimeDispositionRequest",
    "AttendanceRuntimeDispositionResponse",
    "BrowserOfflineAuthorizationBundleResponse",
    "BrowserOfflineAuthorizationPayload",
    "BrowserOfflineAuthorizedPassenger",
    "BrowserOfflineAuthorizedSession",
    "MobileAttendanceDiscardBatchRequest",
    "MobileAttendanceDiscardItemRequest",
]
