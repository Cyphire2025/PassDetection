"""Rooming, QR delivery, and attendance SQLAlchemy models."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
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
        Index("ix_attendance_sessions_group_status", "group_id", "status"),
        Index("ix_attendance_sessions_agency_created", "agency_id", "created_at"),
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


class AttendanceRecordModel(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "passenger_id", name="uq_attendance_records_session_passenger"
        ),
        UniqueConstraint(
            "session_id", "client_event_id", name="uq_attendance_records_session_client_event"
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
