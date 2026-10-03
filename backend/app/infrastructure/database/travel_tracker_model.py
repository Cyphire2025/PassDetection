"""Manual travel readiness, isolated from passport approval and document delivery."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, ForeignKeyConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import Base


class TravelTrackerModel(Base):
    __tablename__ = "travel_tracker"
    __table_args__ = (
        ForeignKeyConstraint(
            ["passenger_id", "agency_id", "group_id"],
            [
                "passport_submissions.id",
                "passport_submissions.agency_id",
                "passport_submissions.group_id",
            ],
            name="fk_travel_tracker_passenger_scope",
            ondelete="CASCADE",
        ),
        Index(
            "ix_travel_tracker_group_marks",
            "agency_id",
            "group_id",
            "visa_applied",
            "flight_booked",
        ),
    )

    passenger_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    visa_applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    flight_booked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    visa_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    flight_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    visa_updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    flight_updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
