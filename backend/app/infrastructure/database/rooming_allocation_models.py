"""Room preferences, allocations and check-in evidence."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import JSONB, Base, _utcnow


class RoomingPassengerPreferenceModel(Base):
    __tablename__ = "rooming_passenger_preferences"
    __table_args__ = (
        UniqueConstraint("hotel_id", "passenger_id", name="uq_rooming_preferences_hotel_passenger"),
        Index("ix_rooming_preferences_hotel_id", "hotel_id"),
        Index("ix_rooming_preferences_passenger_id", "passenger_id"),
        Index("ix_rooming_preferences_hotel_passenger", "hotel_id", "passenger_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hotel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rooming_hotels.id", ondelete="CASCADE"),
        nullable=False,
    )
    passenger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("passport_submissions.id", ondelete="CASCADE"),
        nullable=False,
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
