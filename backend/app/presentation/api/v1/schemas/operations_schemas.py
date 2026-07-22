"""
Operational API Schemas
=======================
Schemas for admin, audit, analytics, and notification endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    agency_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    actor_email: str | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    ip_address: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime


class NotificationResponse(BaseModel):
    id: uuid.UUID
    agency_id: uuid.UUID
    user_id: uuid.UUID | None = None
    type: str
    title: str
    message: str
    entity_type: str | None = None
    entity_id: str | None = None
    is_read: bool
    created_at: datetime
    read_at: datetime | None = None


class AdminOverviewResponse(BaseModel):
    agencies: int
    users: int
    client_groups: int
    passport_submissions: int
    pending_review: int
    client_submitted: int
    failed: int


class PurgePassportDataResponse(BaseModel):
    deleted_client_groups: int
    deleted_passport_submissions: int
    deleted_processing_jobs: int
    deleted_notifications: int
    deleted_audit_logs: int
    deleted_storage_objects: int
    deleted_whatsapp_broadcast_groups: int = 0
    deleted_whatsapp_recipients: int = 0
    deleted_whatsapp_rejected_contacts: int = 0
    deleted_whatsapp_support_contacts: int = 0
    deleted_whatsapp_message_logs: int = 0
    deleted_whatsapp_delivery_states: int = 0


class PlatformSettingsResponse(BaseModel):
    platform_name: str = Field(default="Global Connects Dashboard", min_length=2, max_length=80)
    require_client_email: bool = False
    require_client_phone: bool = False
    duplicate_contact_policy: str = Field(default="block_same_group", pattern="^(block_same_group|allow|block_all)$")
    default_group_status: str = Field(default="active", pattern="^(active|closed)$")
    auto_archive_closed_groups_days: int = Field(default=90, ge=1, le=3650)
    passport_data_retention_days: int = Field(default=365, ge=1, le=3650)
    mrz_review_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    allow_manager_group_creation: bool = True
    audit_log_retention_days: int = Field(default=365, ge=1, le=3650)
    updated_at: datetime | None = None


class UpdatePlatformSettingsRequest(BaseModel):
    platform_name: str = Field(..., min_length=2, max_length=80)
    require_client_email: bool
    require_client_phone: bool
    duplicate_contact_policy: str = Field(..., pattern="^(block_same_group|allow|block_all)$")
    default_group_status: str = Field(..., pattern="^(active|closed)$")
    auto_archive_closed_groups_days: int = Field(..., ge=1, le=3650)
    passport_data_retention_days: int = Field(..., ge=1, le=3650)
    mrz_review_threshold: float = Field(..., ge=0.0, le=1.0)
    allow_manager_group_creation: bool
    audit_log_retention_days: int = Field(..., ge=1, le=3650)


class CreateManagerRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=10, max_length=128)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        from app.core.security.password import validate_password_strength

        validate_password_strength(value)
        return value


class CreateStaffRequest(CreateManagerRequest):
    pass


class DeleteManagerRequest(BaseModel):
    delete_owned_data: bool = False


class DeleteManagerResponse(BaseModel):
    deleted_manager_id: uuid.UUID
    deleted_owned_data: bool
    deleted_client_groups: int = 0
    deleted_passport_submissions: int = 0
    deleted_processing_jobs: int = 0
    deleted_notifications: int = 0
    deleted_audit_logs: int = 0
    deleted_storage_objects: int = 0


class ManagerGroupAccessResponse(BaseModel):
    id: uuid.UUID
    agency_id: uuid.UUID
    name: str
    status: str
    created_by_user_id: uuid.UUID | None = None


class ManagerResponse(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    role: str
    agency_id: uuid.UUID | None
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None
    created_groups: list[ManagerGroupAccessResponse] = Field(default_factory=list)
    assigned_groups: list[ManagerGroupAccessResponse] = Field(default_factory=list)


class AssignManagerGroupsRequest(BaseModel):
    group_ids: list[uuid.UUID] = Field(default_factory=list)


class ManagedAccountResponse(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    role: str
    agency_id: uuid.UUID | None
    agency_name: str | None = None
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class ResetManagedAccountPasswordRequest(BaseModel):
    password: str = Field(..., min_length=10, max_length=128)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        from app.core.security.password import validate_password_strength

        validate_password_strength(value)
        return value


class SetManagedAccountStatusRequest(BaseModel):
    is_active: bool


class DeleteManagedAccountResponse(BaseModel):
    account_id: uuid.UUID
    result: str
    preserved_history: bool


class AnalyticsSummaryResponse(BaseModel):
    status_counts: dict[str, int]
    confidence_buckets: dict[str, int]
    submissions_by_day: dict[str, int]
    average_confidence: float | None
