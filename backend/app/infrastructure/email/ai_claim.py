"""Immutable identity of one leased email analysis task."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class EmailAiClaim:
    analysis_id: uuid.UUID
    agency_id: uuid.UUID
    owner_user_id: uuid.UUID
    connection_id: uuid.UUID
    message_id: uuid.UUID
    provider_account_id: str
    sync_generation: int
    lease_token: str

    def task_kwargs(self) -> dict[str, object]:
        return {
            "analysis_id": str(self.analysis_id),
            "agency_id": str(self.agency_id),
            "owner_user_id": str(self.owner_user_id),
            "connection_id": str(self.connection_id),
            "message_id": str(self.message_id),
            "provider_account_id": self.provider_account_id,
            "sync_generation": self.sync_generation,
            "lease_token": self.lease_token,
        }


EmailAiClaim.__module__ = "app.infrastructure.email.ai_runtime"
