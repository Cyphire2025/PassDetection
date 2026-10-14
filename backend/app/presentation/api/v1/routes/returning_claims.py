"""Thin public returning-claim routes; no full historical data in these responses."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.audit import record_claim_action
from app.application.travellers.authority import active_scope
from app.application.travellers.claims import ReturningClaims
from app.application.travellers.document_challenge import (
    change_document_question,
    reliable_answers,
    verify_document_answers,
)
from app.application.travellers.errors import ReuseError
from app.application.travellers.grants import confirm_claim
from app.application.travellers.matching import phone_candidates, select_candidate
from app.application.travellers.otp import request_code, verify_code
from app.application.travellers.passport_date_proof import prepare_passport_date, verify_passport_date
from app.core.config.traveller_reuse import get_traveller_reuse_settings
from app.domain.services.traveller_verification import DocumentQuestion
from app.domain.value_objects.upload_configuration import configuration_for
from app.infrastructure.database.session import get_db_session
from app.infrastructure.security.traveller_reuse_rate_limiter import TravellerReuseRateLimiter
from app.infrastructure.whatsapp.otp_provider import get_otp_provider
from app.presentation.api.v1.routes.returning_dependencies import (
    CLAIM_COOKIE,
    GRANT_COOKIE,
    claim_secret,
    private_boundary,
    returning_service,
    set_secret_cookie,
)
from app.presentation.api.v1.schemas.returning_schemas import (
    AnswerRequest,
    CandidatePageResponse,
    CandidateSelectRequest,
    ChangeQuestionRequest,
    ClaimStageResponse,
    ClaimStartRequest,
    CodeVerifyRequest,
    ConfirmClaimRequest,
    MaskedCandidateResponse,
    OTPRequestResponse,
    PassportCheckRequest,
    ReturningCapabilitiesResponse,
)
from app.presentation.security.client_ip import trusted_client_ip

router = APIRouter(dependencies=[Depends(private_boundary)])


@router.get("/capabilities", response_model=ReturningCapabilitiesResponse)
async def capabilities(
    group_token: str = Query(min_length=1, max_length=128), session: AsyncSession = Depends(get_db_session),
) -> ReturningCapabilitiesResponse:
    if not get_traveller_reuse_settings().disclosure_enabled:
        return ReturningCapabilitiesResponse(enabled=False)
    try:
        scope = await active_scope(session, group_token=group_token)
    except ReuseError:
        return ReturningCapabilitiesResponse(enabled=False)
    return ReturningCapabilitiesResponse(enabled=True,
        code_label=configuration_for(scope.group).agent_employee_code_label if scope.config.individual_identifier_type else None)


@router.post("/claims", response_model=ClaimStageResponse)
async def start_claim(
    body: ClaimStartRequest, response: Response, service: ReturningClaims = Depends(returning_service),
) -> ClaimStageResponse:
    secret, _ = await service.start(group_token=body.group_token, method=body.method, phone=body.phone_number,
        passport_number=body.passport_number, issuing_country=body.issuing_country,
        document_type=body.document_type, individual_code=body.individual_code)
    set_secret_cookie(response, CLAIM_COOKIE, secret, 600)
    return ClaimStageResponse(stage="contact" if body.method == "phone" else "identify", expires_in_seconds=600)


@router.post("/otp/request", response_model=OTPRequestResponse)
async def request_claim_otp(
    request: Request, secret: str = Depends(claim_secret), service: ReturningClaims = Depends(returning_service),
) -> OTPRequestResponse:
    expires, resend = await request_code(service, secret, provider=get_otp_provider(service.settings),
        ip_address=trusted_client_ip(request), limiter=TravellerReuseRateLimiter())
    return OTPRequestResponse(expires_in_seconds=expires, resend_after_seconds=resend)


@router.post("/otp/verify", response_model=ClaimStageResponse)
async def verify_claim_otp(
    body: CodeVerifyRequest, secret: str = Depends(claim_secret), service: ReturningClaims = Depends(returning_service),
) -> ClaimStageResponse:
    await verify_code(service, secret, body.code)
    return ClaimStageResponse(stage="identify")


@router.get("/candidates", response_model=CandidatePageResponse)
async def masked_candidates(
    secret: str = Depends(claim_secret), service: ReturningClaims = Depends(returning_service),
) -> CandidatePageResponse:
    claim, scope = await service.locked(secret)
    items, narrowing = await phone_candidates(service.session, scope, claim, service.crypto, datetime.now(UTC))
    await record_claim_action(service.session, claim, "candidates_viewed")
    await service.session.commit()
    return CandidatePageResponse(items=[MaskedCandidateResponse(handle=item.handle, label=item.label, passport_hint=item.passport_hint) for item in items], narrowing_required=narrowing)


@router.post("/candidate", response_model=ClaimStageResponse)
async def choose_candidate(
    body: CandidateSelectRequest, secret: str = Depends(claim_secret), service: ReturningClaims = Depends(returning_service),
) -> ClaimStageResponse:
    claim, scope = await service.locked(secret)
    await select_candidate(service.session, scope, claim, service.crypto, body.handle, datetime.now(UTC))
    await service.session.commit()
    return ClaimStageResponse(stage="passport")


@router.post("/passport", response_model=ClaimStageResponse)
async def check_passport(
    body: PassportCheckRequest, secret: str = Depends(claim_secret), service: ReturningClaims = Depends(returning_service),
) -> ClaimStageResponse:
    question = await prepare_passport_date(service, secret, body.model_dump())
    if question is not None:
        return ClaimStageResponse(stage="challenge", questions=[question.value],
            available_questions=[field.value for field in DocumentQuestion], can_change_question=True)
    claim, questions = await service.bind_passport(secret, **body.model_dump())
    available: list[str] = []
    if questions:
        claim, scope = await service.locked(secret)
        _, revision = await service.bound_person(claim, scope, datetime.now(UTC))
        available = [question.value for question in reliable_answers(revision)]
    return ClaimStageResponse(stage="challenge" if questions else "confirm", questions=[q.value for q in questions],
        available_questions=available, can_change_question=len(available) > len(questions))


@router.post("/challenge", response_model=ClaimStageResponse)
async def check_document_answers(
    body: AnswerRequest, secret: str = Depends(claim_secret), service: ReturningClaims = Depends(returning_service),
) -> ClaimStageResponse:
    if await verify_passport_date(service, secret, body.answers):
        return ClaimStageResponse(stage="confirm")
    claim, scope = await service.locked(secret)
    now = datetime.now(UTC)
    _, revision = await service.bound_person(claim, scope, now)
    await verify_document_answers(service.session, claim, revision, body.answers, now)
    await service.session.commit()
    return ClaimStageResponse(stage="recovery" if claim.status == "recovery_confirmation" else "confirm")


@router.post("/challenge/change", response_model=ClaimStageResponse)
async def change_question(
    body: ChangeQuestionRequest, secret: str = Depends(claim_secret), service: ReturningClaims = Depends(returning_service),
) -> ClaimStageResponse:
    question = await prepare_passport_date(service, secret, question=DocumentQuestion(body.field))
    if question is not None:
        return ClaimStageResponse(stage="challenge", questions=[question.value],
            available_questions=[field.value for field in DocumentQuestion], can_change_question=True)
    claim, scope = await service.locked(secret)
    now = datetime.now(UTC)
    _, revision = await service.bound_person(claim, scope, now)
    fields = await change_document_question(service.session, claim, revision, DocumentQuestion(body.field), now)
    await service.session.commit()
    return ClaimStageResponse(stage="challenge", questions=[field.value for field in fields],
        available_questions=[question.value for question in reliable_answers(revision)], can_change_question=True)


@router.post("/confirm", response_model=ClaimStageResponse)
async def confirm_returning_person(
    body: ConfirmClaimRequest, response: Response, secret: str = Depends(claim_secret),
    service: ReturningClaims = Depends(returning_service),
) -> ClaimStageResponse:
    token = await confirm_claim(service, secret, acting_for=body.acting_for, contact_change_confirmed=body.contact_change_confirmed)
    set_secret_cookie(response, GRANT_COOKIE, token, 3600)
    return ClaimStageResponse(stage="review")
