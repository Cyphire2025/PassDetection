"""Create a short-lived qualifier choice before public document upload."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from app.application.dtos.qualifier_selection_dtos import (
    QualifierSelectionOutputDTO,
)
from app.core.logging.logger import get_logger
from app.domain.entities.entities import QualifierSelection
from app.domain.exceptions.exceptions import (
    EntityNotFoundError,
    GroupClosedError,
    ValidationError,
)
from app.domain.repositories.interfaces import (
    IClientGroupRepository,
    IQualifierSelectionRepository,
)
from app.domain.value_objects.qualifier_relations import (
    hash_qualifier_selection_token,
)

QUALIFIER_SELECTION_TTL = timedelta(hours=2)
logger = get_logger(__name__)


class CreateQualifierSelectionUseCase:
    def __init__(
        self,
        client_group_repo: IClientGroupRepository,
        qualifier_selection_repo: IQualifierSelectionRepository,
    ) -> None:
        self._client_group_repo = client_group_repo
        self._selection_repo = qualifier_selection_repo

    async def execute(
        self,
        *,
        group_token: str,
        is_self: bool,
        relation_code: str | None,
    ) -> QualifierSelectionOutputDTO:
        group = await self._client_group_repo.get_by_token(group_token)
        if group is None:
            raise EntityNotFoundError("ClientGroup", "upload-link")
        if not group.is_active():
            raise GroupClosedError()
        if not group.relation_with_qualifier_enabled:
            raise ValidationError(
                "Relation with Qualifier is not enabled for this upload link.",
                field="relation_with_qualifier_enabled",
            )

        raw_token = secrets.token_urlsafe(32)
        selected_at = datetime.now(tz=UTC)
        selection = QualifierSelection.create(
            group_id=group.id,
            token_hash=hash_qualifier_selection_token(raw_token),
            is_self=is_self,
            relation_code=relation_code,
            selected_at=selected_at,
            expires_at=selected_at + QUALIFIER_SELECTION_TTL,
        )
        await self._selection_repo.save(selection)
        logger.info(
            "qualifier_selection_created",
            selection_id=str(selection.id),
            group_id=str(group.id),
        )
        return QualifierSelectionOutputDTO(
            is_self=selection.is_self,
            relation_code=selection.relation_code,
            relation_label=selection.relation_label,
            selected_at=selection.selected_at,
            expires_at=selection.expires_at,
            status="active",
            selection_token=raw_token,
        )
