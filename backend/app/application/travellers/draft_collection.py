"""Final-only qualifier attachment shared by fresh and returning drafts."""
from app.application.travellers.draft_store import DraftStore
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.fresh_draft_contracts import FreshCollection
from app.application.use_cases.passports.submit_passport_use_case import SubmitPassportUseCase
from app.domain.entities.entities import ClientGroup, PassportSubmission
from app.domain.value_objects.qualifier_relations import require_enabled_qualifier_choice
from app.domain.value_objects.upload_configuration import configuration_for
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.repositories.qualifier_selection_repository import (
    QualifierSelectionRepository,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository


async def attach_draft_qualifier(service: DraftStore, group: ClientGroup,
    source: PassportSubmission, collection: FreshCollection,
) -> None:
    config = configuration_for(group)
    if not group.relation_with_qualifier_enabled or not (
        config.required("relation_with_qualifier") or collection.qualifier_selection_token
    ):
        return
    creator = SubmitPassportUseCase(ClientGroupRepository(service.session),
        PassportSubmissionRepository(service.session), MinioStorageRepository(),
        qualifier_selection_repo=QualifierSelectionRepository(service.session))
    selection, prior = await creator._require_qualifier_selection(group_id=group.id,
        selection_token=collection.qualifier_selection_token, upload_idempotency_key=source.upload_idempotency_key)
    if prior is not None and prior.id != source.id:
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    require_enabled_qualifier_choice(group, is_self=selection.is_self, relation_code=selection.relation_code)
    source.attach_qualifier_selection(selection)
