"""Fresh drafts use a browser secret plus per-member upload capability.

No existing traveller is selected or disclosed. Scope is one active group, with
O(1) indexed reads. Expiry is fixed on creation and never extended by autosave.
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.application.security.public_upload_capability import require_active_public_upload
from app.application.travellers.draft_contracts import DraftPayload, DraftView
from app.application.travellers.draft_retention import discard_draft_images
from app.application.travellers.draft_store import DraftStore
from app.application.travellers.drafts import DRAFT_LIFETIME, draft_view
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.history import question_version
from app.core.security.upload_session import is_valid_upload_credential
from app.domain.services.traveller_verification import utc
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerReturningDraftModel as Draft,
)
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.platform_policy_repository import PlatformPolicyRepository


def fresh_secret(service: DraftStore, group_token: str, browser_secret: str, upload_session_id: str) -> str:
    if not is_valid_upload_credential(browser_secret) or not is_valid_upload_credential(upload_session_id):
        raise ReuseError(ReuseReason.EXPIRED)
    return service.crypto.digest("fresh-draft-capability", group_token, browser_secret, upload_session_id)


async def active_fresh_group(service: DraftStore, group_token: str, *, exclusive: bool = False) -> ClientGroupModel:
    group = await service.session.scalar(select(ClientGroupModel).where(ClientGroupModel.token == group_token)
        .with_for_update(of=ClientGroupModel, read=not exclusive).execution_options(populate_existing=True))
    if group is None:
        raise ReuseError(ReuseReason.UNAVAILABLE)
    require_active_public_upload(ClientGroupRepository._to_entity(group))
    return group


async def require_fresh_draft(service: DraftStore, group_token: str, secret: str, *, submitted: bool = False, exclusive_group: bool = False) -> Draft:
    group = await active_fresh_group(service, group_token, exclusive=exclusive_group)
    draft = await service.session.scalar(select(Draft).where(Draft.secret_hash == service.crypto.digest("returning-draft", secret),
        Draft.agency_id == group.agency_id, Draft.group_id == group.id, Draft.mode == "fresh")
        .with_for_update().execution_options(populate_existing=True))
    if draft is None or utc(draft.expires_at) <= datetime.now(UTC) or draft.status not in ({"active", "submitted"} if submitted else {"active"}):
        raise ReuseError(ReuseReason.EXPIRED)
    if draft.company_id != group.company_id:
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    return draft


async def start_fresh_draft(service: DraftStore, group_token: str, secret: str, upload_session_id: str) -> DraftView:
    group = await active_fresh_group(service, group_token, exclusive=True)
    digest = service.crypto.digest("returning-draft", secret)
    draft = await service.session.scalar(select(Draft).where(Draft.secret_hash == digest).with_for_update())
    if draft is None:
        now = datetime.now(UTC)
        policy = await PlatformPolicyRepository(service.session).load()
        draft = Draft(id=uuid.uuid4(), agency_id=group.agency_id, company_id=group.company_id, group_id=group.id,
            mode="fresh", upload_session_hash=service.crypto.digest("fresh-draft-session", upload_session_id),
            secret_hash=digest, status="active", revision=1, fields_revision=1, created_at=now, expires_at=now+DRAFT_LIFETIME,
            contact_revision=0, profile_revision=0, authorization_version=0, review_version=question_version(group, policy),
            payload_ciphertext=service.crypto.encrypt(DraftPayload().model_dump_json()))
        service.session.add(draft)
        await service.session.flush()
    else:
        draft = await require_fresh_draft(service, group_token, secret, submitted=True)
        await discard_draft_images(service, draft)
    result = await draft_view(service, draft)
    await service.session.commit()
    return result
