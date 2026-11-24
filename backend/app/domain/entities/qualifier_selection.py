"""Time-bound qualifier choices captured before document collection."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.domain.entities.factories import _new_uuid, _utcnow
from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.qualifier_relations import normalize_qualifier_choice


@dataclass
class QualifierSelection:
    """A short-lived, server-persisted choice made before document upload."""

    id: uuid.UUID
    group_id: uuid.UUID
    token_hash: str
    is_self: bool
    relation_code: str | None
    relation_label: str
    selected_at: datetime
    expires_at: datetime
    created_at: datetime

    @classmethod
    def create(
        cls,
        *,
        group_id: uuid.UUID,
        token_hash: str,
        is_self: bool,
        relation_code: str | None,
        selected_at: datetime,
        expires_at: datetime,
        other_relation: str | None = None,
    ) -> QualifierSelection:
        if expires_at <= selected_at:
            raise ValidationError(
                "Qualifier selection expiry must be after selection time.",
                field="expires_at",
            )
        canonical_self, canonical_code, label = normalize_qualifier_choice(
            is_self=is_self,
            relation_code=relation_code,
            other_relation=other_relation,
        )
        return cls(
            id=_new_uuid(),
            group_id=group_id,
            token_hash=token_hash,
            is_self=canonical_self,
            relation_code=canonical_code,
            relation_label=label,
            selected_at=selected_at,
            expires_at=expires_at,
            created_at=selected_at,
        )

    def is_expired(self, *, now: datetime | None = None) -> bool:
        return self.expires_at <= (now or _utcnow())
