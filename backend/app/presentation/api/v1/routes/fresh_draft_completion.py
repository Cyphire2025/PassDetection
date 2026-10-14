"""Publish one fresh source using the existing validation and OTP workflow."""
import hmac
import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.application.travellers.draft_store import FreshDraftStore
from app.application.travellers.drafts import draft_payload
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.fresh_draft_contracts import FreshCollection, FreshDraftComplete
from app.application.travellers.fresh_drafts import active_fresh_group, require_fresh_draft
from app.application.travellers.fresh_publication import prepare_fresh_source
from app.application.use_cases.passports.client_submit_passport_use_case import (
    ClientSubmitPassportUseCase,
)
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.repositories.platform_policy_repository import PlatformPolicyRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes.fresh_draft_dependencies import (
    fresh_store,
    fresh_token,
    upload_session,
)
from app.presentation.api.v1.routes.passport_routes.submission_contact import (
    require_verified_submission_contact,
)
from app.presentation.api.v1.routes.passport_routes.submission_execution import (
    execute_client_review,
)
from app.presentation.api.v1.routes.passport_routes.submission_side_effects import (
    stage_submission_side_effects,
)
from app.presentation.api.v1.routes.returning_dependencies import private_boundary
from app.presentation.api.v1.schemas.passport_schemas import ClientSubmitPassportRequest

router = APIRouter(dependencies=[Depends(private_boundary)])


class FreshDraftResult(BaseModel):
    source_submission_id: uuid.UUID
    status: Literal["submitted", "needs_review", "ai_approved", "staff_approved"]


@router.post("/{group_token}/complete", response_model=FreshDraftResult)
async def complete(group_token: str, body: FreshDraftComplete, secret: str = Depends(fresh_token),
    session_id: str = Depends(upload_session), service: FreshDraftStore = Depends(fresh_store),
) -> FreshDraftResult:
    draft = await require_fresh_draft(service, group_token, secret, submitted=True, exclusive_group=True)
    digest = service.crypto.digest("fresh-draft-complete", body.model_dump_json())
    if draft.status == "submitted":
        if draft.completion_key != body.idempotency_key or not hmac.compare_digest(draft.completion_digest or "", digest):
            raise ReuseError(ReuseReason.REVISION_CONFLICT)
        result = FreshDraftResult.model_validate({"source_submission_id": draft.source_submission_id, "status": draft.result_status})
        await service.session.commit()
        return result
    if draft.revision != body.expected_revision or draft.upload_session_hash != service.crypto.digest("fresh-draft-session", session_id):
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    payload = draft_payload(service, draft)
    collection = (payload.collection or FreshCollection()).model_dump(exclude={"acquisition_mode", "visa_photo_source", "qualifier_selection_token"})
    request = ClientSubmitPassportRequest.model_validate({**{k: v for k, v in payload.current_details.items() if k != "client_name"},
        **collection, "group_token": group_token, "confirmed_fields": payload.passport_fields,
        "phone_verification_id": body.phone_verification_id,
        "custom_answers": [{"question_id": k, "value": v} for k, v in payload.custom_answers.items()],
        "custom_detail_answers": [{"detail_id": k, "value": v} for k, v in payload.custom_detail_answers.items()]})
    group = await active_fresh_group(service, group_token)
    source_id, _ = await prepare_fresh_source(service, draft, group, payload, upload_session_id=session_id,
        phone_proof_id=body.phone_verification_id, email=str(request.client_email), phone=request.client_phone)
    proof = await require_verified_submission_contact(service.session, submission_id=source_id,
        body=request, upload_session_id=session_id)
    use_case = ClientSubmitPassportUseCase(PassportSubmissionRepository(service.session), ClientGroupRepository(service.session),
        MinioStorageRepository(), PlatformPolicyRepository(service.session))
    output = await execute_client_review(use_case, source_id, request)
    await stage_submission_side_effects(service.session, result=output, contact_proof=proof, sync_broadcast_contacts=False)
    draft.status, draft.completion_key, draft.completion_digest = "submitted", body.idempotency_key, digest
    draft.source_submission_id, draft.result_status = output.id, output.status
    await service.session.commit()
    return FreshDraftResult.model_validate({"source_submission_id": output.id, "status": output.status})
