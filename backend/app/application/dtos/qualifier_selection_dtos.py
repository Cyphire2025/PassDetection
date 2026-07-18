"""Application DTOs for the public qualifier-selection step."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class QualifierSelectionOutputDTO:
    is_self: bool
    relation_code: str | None
    relation_label: str
    selected_at: datetime
    expires_at: datetime
    status: str
    submission_id: uuid.UUID | None = None
    selection_token: str | None = None
