"""Neutral stored-schedule projection shared by the website and MCP read."""

from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict
from uuid import UUID


class PassportRetentionProjection(TypedDict):
    group_id: UUID
    passport_purge_at: datetime | None
    passport_retention_days_applied: int | None


@dataclass(frozen=True, slots=True)
class PassportRetentionSchedule:
    group_id: UUID
    agency_id: UUID
    passport_purge_at: datetime | None
    passport_retention_days_applied: int | None

    def project(self) -> PassportRetentionProjection:
        return {
            "group_id": self.group_id,
            "passport_purge_at": self.passport_purge_at,
            "passport_retention_days_applied": self.passport_retention_days_applied,
        }
