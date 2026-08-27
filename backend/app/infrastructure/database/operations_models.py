"""Rooming, QR delivery, and attendance SQLAlchemy models."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import JSONB, Base, _utcnow


class RoomingHotelModel(Base):
    __tablename__ = "rooming_hotels"
    __table_args__ = (Index("ix_rooming_hotels_group_created", "group_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hotel_name: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    check_in_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    check_out_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    allocation_priority_fields: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    allocation_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    allocation_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    allocation_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )


class AttendanceDiscardTombstoneModel(Base):
    """Privacy-safe, idempotent evidence that a local scan was discarded."""

    __tablename__ = "attendance_discard_tombstones"
    __table_args__ = (
        UniqueConstraint(
            "agency_id",
            "coordinator_user_id",
            "discard_event_id",
            name="uq_attendance_discard_event",
        ),
        ForeignKeyConstraint(
            ["session_id", "agency_id", "group_id"],
            [
                "attendance_sessions.id",
                "attendance_sessions.agency_id",
                "attendance_sessions.group_id",
            ],
            name="fk_attendance_discard_session_tenant_group",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["runtime_registration_id", "agency_id", "coordinator_user_id"],
            [
                "attendance_runtime_registrations.id",
                "attendance_runtime_registrations.agency_id",
                "attendance_runtime_registrations.coordinator_user_id",
            ],
            name="fk_attendance_discard_runtime_tenant_coordinator",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "length(scan_reference) = 64",
            name="ck_attendance_discard_scan_reference",
        ),
        CheckConstraint(
            "reason_category IN ('operator_discard', 'coordinator_confirmed_rescan', "
            "'wrong_group', 'expired_authorization', 'activity_closed', 'duplicate', "
            "'duplicate_local_evidence', 'passenger_not_attending', 'privacy_or_data_error', "
            "'server_rejected', 'server_terminal_rejection', 'corrupted_entry', 'other')",
            name="ck_attendance_discard_reason",
        ),
        CheckConstraint(
            "status IN ('accepted', 'reconciled', 'overridden')",
            name="ck_attendance_discard_status",
        ),
        CheckConstraint(
            "received_at >= discarded_at AND retention_expires_at > received_at",
            name="ck_attendance_discard_time_order",
        ),
        Index(
            "ix_attendance_discard_session_received",
            "session_id",
            "received_at",
        ),
        Index(
            "ix_attendance_discard_retention",
            "retention_expires_at",
            "id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="RESTRICT"),
        nullable=False,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_sessions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    coordinator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    runtime_registration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_runtime_registrations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    discard_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    scan_reference: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_category: Mapped[str] = mapped_column(String(32), nullable=False)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discarded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="accepted",
        server_default="accepted",
    )
    retention_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reconciliation_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class RoomingHotelPassengerModel(Base):
    """Exclusive passenger membership in one hotel within a client group."""

    __tablename__ = "rooming_hotel_passengers"
    __table_args__ = (
        UniqueConstraint(
            "group_id",
            "passenger_id",
            name="uq_rooming_hotel_passengers_group_passenger",
        ),
        UniqueConstraint(
            "hotel_id",
            "passenger_id",
            name="uq_rooming_hotel_passengers_hotel_passenger",
        ),
        Index(
            "ix_rooming_hotel_passengers_group_hotel",
            "group_id",
            "hotel_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hotel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rooming_hotels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    passenger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_vip: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class RoomingRoomModel(Base):
    __tablename__ = "rooming_rooms"
    __table_args__ = (
        UniqueConstraint("hotel_id", "room_number", name="uq_rooming_rooms_hotel_number"),
        Index("ix_rooming_rooms_hotel_number", "hotel_id", "room_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hotel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rooming_hotels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    room_number: Mapped[str] = mapped_column(String(32), nullable=False)
    room_type: Mapped[str] = mapped_column(String(16), nullable=False, default="twin")
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    allocation_tag: Mapped[str] = mapped_column(String(16), nullable=False, default="mixed")
    roommate_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_saved: Mapped[bool] = mapped_column(default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class RoomingPassengerPreferenceModel(Base):
    __tablename__ = "rooming_passenger_preferences"
    __table_args__ = (
        UniqueConstraint("hotel_id", "passenger_id", name="uq_rooming_preferences_hotel_passenger"),
        Index("ix_rooming_preferences_hotel_passenger", "hotel_id", "passenger_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hotel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rooming_hotels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    passenger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    allocation_tag: Mapped[str] = mapped_column(String(16), nullable=False, default="unspecified")
    special_requests: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    roommate_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class RoomingAssignmentModel(Base):
    __tablename__ = "rooming_assignments"
    __table_args__ = (
        UniqueConstraint("hotel_id", "passenger_id", name="uq_rooming_assignments_hotel_passenger"),
        UniqueConstraint("room_id", "passenger_id", name="uq_rooming_assignments_room_passenger"),
        Index("ix_rooming_assignments_room_position", "room_id", "position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hotel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rooming_hotels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rooming_rooms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    passenger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class RoomingCheckinModel(Base):
    __tablename__ = "rooming_checkins"
    __table_args__ = (
        UniqueConstraint("hotel_id", "passenger_id", name="uq_rooming_checkins_hotel_passenger"),
        Index(
            "ix_rooming_checkins_hotel_status",
            "hotel_id",
            "checked_in",
            "key_issued",
            "welcome_letter_issued",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hotel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rooming_hotels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rooming_rooms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    passenger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    checked_in: Mapped[bool] = mapped_column(default=False, nullable=False)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    key_issued: Mapped[bool] = mapped_column(default=False, nullable=False)
    key_issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    welcome_letter_issued: Mapped[bool] = mapped_column(default=False, nullable=False)
    welcome_letter_issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class PassengerQRTokenModel(Base):
    __tablename__ = "passenger_qr_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_passenger_qr_tokens_token_hash"),
        Index("ix_passenger_qr_tokens_active_passenger", "passenger_id", "is_active"),
        Index("ix_passenger_qr_tokens_agency_active", "agency_id", "is_active"),
        Index(
            "uq_passenger_qr_tokens_one_active_per_passenger",
            "passenger_id",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    passenger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    qr_payload: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class PassengerQrWhatsAppDeliveryModel(Base):
    """Durable, idempotent WhatsApp delivery state for one QR token version."""

    __tablename__ = "passenger_qr_whatsapp_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "qr_token_id",
            name="uq_passenger_qr_whatsapp_delivery_token",
        ),
        Index(
            "ix_passenger_qr_whatsapp_delivery_group_status",
            "group_id",
            "status",
        ),
        Index(
            "ix_passenger_qr_whatsapp_delivery_send_batch",
            "send_batch_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    passenger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    qr_token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passenger_qr_tokens.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    broadcast_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_broadcast_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_broadcast_recipients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    send_batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    passenger_name: Mapped[str] = mapped_column(String(255), nullable=False)
    passport_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    phone_number: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_phone_number: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )
    template_name: Mapped[str] = mapped_column(String(255), nullable=False)
    template_parameter_values: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_message_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
    )
    provider_media_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
    provider_status_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )


class AttendanceSessionModel(Base):
    __tablename__ = "attendance_sessions"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "agency_id",
            name="uq_attendance_sessions_id_agency",
        ),
        UniqueConstraint(
            "id",
            "agency_id",
            "group_id",
            name="uq_attendance_sessions_id_agency_group",
        ),
        CheckConstraint(
            "(scheduled_starts_at IS NULL AND scheduled_ends_at IS NULL) OR "
            "(scheduled_starts_at IS NOT NULL AND scheduled_ends_at IS NOT NULL "
            "AND scheduled_ends_at > scheduled_starts_at)",
            name="ck_attendance_sessions_scheduled_window",
        ),
        CheckConstraint(
            "schedule_version >= 1",
            name="ck_attendance_sessions_schedule_version",
        ),
        CheckConstraint(
            "schedule_timezone IS NULL OR "
            "(length(schedule_timezone) BETWEEN 1 AND 64 "
            "AND schedule_timezone = trim(schedule_timezone))",
            name="ck_attendance_sessions_schedule_timezone",
        ),
        Index("ix_attendance_sessions_group_status", "group_id", "status"),
        Index("ix_attendance_sessions_agency_created", "agency_id", "created_at"),
        Index(
            "ix_attendance_sessions_group_schedule",
            "group_id",
            "scheduled_starts_at",
            "scheduled_ends_at",
        ),
        Index(
            "uq_attendance_sessions_active_group_name",
            "group_id",
            "normalized_name",
            unique=True,
            postgresql_where=text("status IN ('draft', 'active') AND id = canonical_session_id"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(160), nullable=False)
    canonical_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "draft",
            "active",
            "completed",
            "cancelled",
            name="attendance_session_status_enum",
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
        default="draft",
        index=True,
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    scheduled_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    schedule_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schedule_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )


class AttendanceRuntimeRegistrationModel(Base):
    """Privacy-safe coordinator installation/runtime registration."""

    __tablename__ = "attendance_runtime_registrations"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "agency_id",
            "coordinator_user_id",
            name="uq_attendance_runtime_id_tenant_coordinator",
        ),
        UniqueConstraint(
            "agency_id",
            "coordinator_user_id",
            "runtime_identifier_hash",
            name="uq_attendance_runtime_identifier",
        ),
        ForeignKeyConstraint(
            ["coordinator_user_id", "agency_id"],
            ["users.id", "users.agency_id"],
            name="fk_attendance_runtime_coordinator_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "runtime_kind IN ('native_mobile', 'pwa', 'webview', 'legacy_account')",
            name="ck_attendance_runtime_kind",
        ),
        CheckConstraint(
            "status IN ('active', 'revoked', 'expired', 'lost', 'replaced')",
            name="ck_attendance_runtime_status",
        ),
        CheckConstraint(
            "length(runtime_identifier_hash) = 64",
            name="ck_attendance_runtime_identifier_hash",
        ),
        CheckConstraint(
            "expires_at > registered_at",
            name="ck_attendance_runtime_expiry",
        ),
        CheckConstraint(
            "(status = 'active' AND revoked_at IS NULL) OR "
            "(status <> 'active' AND revoked_at IS NOT NULL)",
            name="ck_attendance_runtime_revocation_shape",
        ),
        Index(
            "ix_attendance_runtime_coordinator_status",
            "agency_id",
            "coordinator_user_id",
            "status",
            "expires_at",
        ),
        Index(
            "ix_attendance_runtime_native_session",
            "native_mobile_session_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    coordinator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    runtime_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    runtime_identifier_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    native_mobile_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mobile_device_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="active",
        server_default="active",
    )
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    replaced_by_runtime_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_runtime_registrations.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )


class AttendanceSessionRuntimeParticipantModel(Base):
    """A runtime that produced evidence and must participate in closeout."""

    __tablename__ = "attendance_session_runtime_participants"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "runtime_registration_id",
            name="uq_attendance_session_runtime_participant",
        ),
        ForeignKeyConstraint(
            ["session_id", "agency_id"],
            ["attendance_sessions.id", "attendance_sessions.agency_id"],
            name="fk_attendance_participant_session_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["runtime_registration_id", "agency_id", "coordinator_user_id"],
            [
                "attendance_runtime_registrations.id",
                "attendance_runtime_registrations.agency_id",
                "attendance_runtime_registrations.coordinator_user_id",
            ],
            name="fk_attendance_participant_runtime_tenant_coordinator",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "participation_source IN ('scan', 'checkpoint', 'discard', 'legacy')",
            name="ck_attendance_participant_source",
        ),
        CheckConstraint(
            "last_participated_at >= first_participated_at",
            name="ck_attendance_participant_time_order",
        ),
        Index(
            "ix_attendance_participants_session_coordinator",
            "session_id",
            "coordinator_user_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    coordinator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    runtime_registration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_runtime_registrations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    participation_source: Mapped[str] = mapped_column(String(16), nullable=False)
    first_participated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    last_participated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )


class AttendanceCloseoutCheckpointModel(Base):
    """Latest count-only closeout evidence for one coordinator and activity."""

    __tablename__ = "attendance_closeout_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "coordinator_user_id",
            "runtime_registration_id",
            name="uq_attendance_closeout_checkpoint_runtime",
        ),
        ForeignKeyConstraint(
            ["session_id", "agency_id"],
            ["attendance_sessions.id", "attendance_sessions.agency_id"],
            name="fk_attendance_closeout_session_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["runtime_registration_id", "agency_id", "coordinator_user_id"],
            [
                "attendance_runtime_registrations.id",
                "attendance_runtime_registrations.agency_id",
                "attendance_runtime_registrations.coordinator_user_id",
            ],
            name="fk_attendance_closeout_runtime_tenant_coordinator",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_attendance_closeout_legacy_account",
            "session_id",
            "coordinator_user_id",
            unique=True,
            postgresql_where=text("runtime_registration_id IS NULL"),
            sqlite_where=text("runtime_registration_id IS NULL"),
        ),
        CheckConstraint(
            "pending_count >= 0 AND sending_count >= 0 AND retryable_count >= 0 "
            "AND needs_review_count >= 0 AND unreviewed_rejected_count >= 0",
            name="ck_attendance_closeout_checkpoint_nonnegative_counts",
        ),
        CheckConstraint(
            "((pending_count + sending_count + retryable_count = 0 "
            "AND oldest_pending_age_seconds IS NULL) OR "
            "(pending_count + sending_count + retryable_count > 0 "
            "AND oldest_pending_age_seconds >= 0))",
            name="ck_attendance_closeout_checkpoint_oldest_pending",
        ),
        Index(
            "ix_attendance_closeout_checkpoints_session_reported",
            "session_id",
            "reported_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    coordinator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    runtime_registration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_runtime_registrations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    pending_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sending_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retryable_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    needs_review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unreviewed_rejected_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    oldest_pending_age_seconds: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    reported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )


class AttendanceRecordModel(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "passenger_id", name="uq_attendance_records_session_passenger"
        ),
        UniqueConstraint(
            "session_id", "client_event_id", name="uq_attendance_records_session_client_event"
        ),
        ForeignKeyConstraint(
            ["runtime_registration_id", "agency_id", "coordinator_user_id"],
            [
                "attendance_runtime_registrations.id",
                "attendance_runtime_registrations.agency_id",
                "attendance_runtime_registrations.coordinator_user_id",
            ],
            name="fk_attendance_record_runtime_tenant_coordinator",
            ondelete="RESTRICT",
        ),
        Index("ix_attendance_records_agency_session", "agency_id", "session_id"),
        Index("ix_attendance_records_coordinator_scanned", "coordinator_user_id", "scanned_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    passenger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    coordinator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    sync_source: Mapped[str] = mapped_column(
        Enum(
            "online",
            "offline",
            name="attendance_scan_source_enum",
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
        default="online",
    )
    client_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    device_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    runtime_registration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_runtime_registrations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class AttendanceScanBatchModel(Base):
    """Durable identity for one bounded browser attendance drain request."""

    __tablename__ = "attendance_scan_batches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "agency_id", "group_id"],
            [
                "attendance_sessions.id",
                "attendance_sessions.agency_id",
                "attendance_sessions.group_id",
            ],
            name="fk_attendance_scan_batch_session_tenant_group",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["runtime_registration_id", "agency_id", "coordinator_user_id"],
            [
                "attendance_runtime_registrations.id",
                "attendance_runtime_registrations.agency_id",
                "attendance_runtime_registrations.coordinator_user_id",
            ],
            name="fk_attendance_scan_batch_runtime_tenant_coordinator",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "length(request_fingerprint) = 64",
            name="ck_attendance_scan_batch_fingerprint",
        ),
        CheckConstraint(
            "item_count BETWEEN 1 AND 50",
            name="ck_attendance_scan_batch_item_count",
        ),
        Index(
            "ix_attendance_scan_batches_session_created",
            "session_id",
            "created_at",
        ),
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_groups.id", ondelete="RESTRICT"),
        nullable=False,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_sessions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    coordinator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    runtime_registration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_runtime_registrations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )


class AttendanceScanBatchResultModel(Base):
    """Privacy-minimized authoritative result for one idempotent batch item."""

    __tablename__ = "attendance_scan_batch_results"
    __table_args__ = (
        UniqueConstraint(
            "agency_id",
            "session_id",
            "client_event_id",
            name="uq_attendance_scan_batch_result_event",
        ),
        CheckConstraint(
            "length(request_fingerprint) = 64",
            name="ck_attendance_scan_batch_result_fingerprint",
        ),
        CheckConstraint(
            "outcome IN ('counted', 'duplicate', 'rejected')",
            name="ck_attendance_scan_batch_result_outcome",
        ),
        CheckConstraint(
            "(outcome IN ('counted', 'duplicate') AND passenger_id IS NOT NULL "
            "AND error_code IS NULL AND retryable = false) OR "
            "(outcome = 'rejected' AND passenger_id IS NULL AND error_code IS NOT NULL)",
            name="ck_attendance_scan_batch_result_shape",
        ),
        Index(
            "ix_attendance_scan_batch_results_batch_order",
            "batch_id",
            "request_ordinal",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_scan_batches.batch_id", ondelete="CASCADE"),
        nullable=False,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_sessions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    coordinator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    client_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    passenger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
