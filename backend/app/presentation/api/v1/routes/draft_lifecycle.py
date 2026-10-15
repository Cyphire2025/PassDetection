"""Capability-scoped image disposal and temporary active-form presence."""
from fastapi import APIRouter, Depends

from app.application.travellers.claims import ReturningClaims
from app.application.travellers.draft_activity import (
    record_draft_activity,
    require_returning_presence,
)
from app.application.travellers.draft_contracts import DraftView
from app.application.travellers.draft_retention import (
    DraftActivity,
    DraftDiscard,
    discard_draft_images,
)
from app.application.travellers.draft_store import FreshDraftStore
from app.application.travellers.drafts import draft_view, require_draft
from app.application.travellers.fresh_drafts import require_fresh_draft
from app.presentation.api.v1.routes.fresh_draft_dependencies import fresh_store, fresh_token
from app.presentation.api.v1.routes.returning_dependencies import (
    grant_secret,
    private_boundary,
    returning_service,
)
from app.presentation.api.v1.routes.returning_draft import draft_secret

router = APIRouter(dependencies=[Depends(private_boundary)])


@router.post("/returning/draft/discard-documents", response_model=DraftView)
async def discard_returning(body: DraftDiscard, secret: str = Depends(draft_secret),
    token: str = Depends(grant_secret), service: ReturningClaims = Depends(returning_service),
) -> DraftView:
    draft = await require_draft(service, token, secret, submitted=True)
    await discard_draft_images(service, draft, through_revision=body.expected_revision)
    result = await draft_view(service, draft)
    await service.session.commit()
    return result


@router.post("/public-drafts/{group_token}/discard-documents", response_model=DraftView)
async def discard_fresh(group_token: str, body: DraftDiscard, secret: str = Depends(fresh_token),
    service: FreshDraftStore = Depends(fresh_store),
) -> DraftView:
    draft = await require_fresh_draft(service, group_token, secret, submitted=True)
    await discard_draft_images(service, draft, through_revision=body.expected_revision)
    result = await draft_view(service, draft)
    await service.session.commit()
    return result


@router.post("/returning/draft/activity", response_model=DraftActivity)
async def returning_activity(secret: str = Depends(draft_secret),
    service: ReturningClaims = Depends(returning_service),
) -> DraftActivity:
    result = await record_draft_activity(service, await require_returning_presence(service, secret))
    await service.session.commit()
    return result


@router.post("/public-drafts/{group_token}/activity", response_model=DraftActivity)
async def fresh_activity(group_token: str, secret: str = Depends(fresh_token),
    service: FreshDraftStore = Depends(fresh_store),
) -> DraftActivity:
    result = await record_draft_activity(service, await require_fresh_draft(service, group_token, secret))
    await service.session.commit()
    return result
