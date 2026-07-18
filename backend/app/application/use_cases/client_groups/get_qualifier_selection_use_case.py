"""Resume one persisted qualifier choice without exposing unrelated records."""

from __future__ import annotations

from app.application.dtos.qualifier_selection_dtos import (
    QualifierSelectionOutputDTO,
)
from app.domain.exceptions.exceptions import EntityNotFoundError, GroupClosedError
from app.domain.repositories.interfaces import (
    IClientGroupRepository,
    IQualifierSelectionRepository,
)
from app.domain.value_objects.qualifier_relations import (
    hash_qualifier_selection_token,
)


class GetQualifierSelectionUseCase:
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
        selection_token: str,
    ) -> QualifierSelectionOutputDTO:
        group = await self._client_group_repo.get_by_token(group_token)
        if group is None:
            raise EntityNotFoundError("ClientGroup", "upload-link")
        if not group.is_active():
            raise GroupClosedError()
        selection = await self._selection_repo.get_by_token_hash(
            group.id,
            hash_qualifier_selection_token(selection_token),
        )
        if selection is None:
            raise EntityNotFoundError("QualifierSelection", "selection")
        submission_id = await self._selection_repo.get_submission_id(selection.id)
        status = (
            "consumed"
            if submission_id is not None
            else "expired"
            if selection.is_expired()
            else "active"
        )
        return QualifierSelectionOutputDTO(
            is_self=selection.is_self,
            relation_code=selection.relation_code,
            relation_label=selection.relation_label,
            selected_at=selection.selected_at,
            expires_at=selection.expires_at,
            status=status,
            submission_id=submission_id,
        )
