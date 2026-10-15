"""Observational equivalents for website reads which also mint files or redeliver jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException, Query
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.client_group_dtos import client_group_output_from_entity
from app.application.dtos.passport_dtos import passport_submission_output_from_entity
from app.application.mcp.credentials import utc
from app.application.mcp.delivery_reads import DELIVERY_MODELS
from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User
from app.domain.value_objects.passport_image_crop import PassportImageType
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassengerQRTokenModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
    WhatsAppBroadcastSourceContactModel,
    WhatsAppBroadcastSupportContactModel,
    WhatsAppProviderMessageBindingModel,
    WhatsAppProviderReceiptModel,
    WhatsAppRecipientMessageStateModel,
    WhatsAppTravellerPhoneOverrideModel,
)
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.repositories.sensitive_read_audit import record_sensitive_read
from app.presentation.api.v1.schemas.client_group_schemas import ClientGroupResponse
from app.presentation.api.v1.schemas.document_distribution_schemas import DocumentBatchResponse
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportSubmissionResponse,
    PassportVisaAiImageJobResponse,
)


async def group_details(group_id: UUID, current_user: User, session: AsyncSession) -> ClientGroupResponse:
    group = await ClientGroupRepository(session).get_by_id(group_id)
    if group is None:
        raise HTTPException(404, "Group not found")
    await AuthorizationPolicy(session).require_view_group(current_user, group)
    dto = client_group_output_from_entity(group)
    return ClientGroupResponse.model_validate(dto)


async def passport_details(submission_id: UUID, current_user: User, session: AsyncSession) -> PassportSubmissionResponse:
    submission = await PassportSubmissionRepository(session).get_by_id(submission_id)
    if submission is None:
        raise HTTPException(404, "Passport not found")
    await AuthorizationPolicy(session).require_view_passport(current_user, submission)
    job = await PassportProcessingJobRepository(session).latest_for_submission(submission.id)
    dto = passport_submission_output_from_entity(submission, job=job)
    await record_sensitive_read(session, user=current_user, kind="detail",
        agency_id=submission.agency_id, entity_id=submission.id)
    token = await session.scalar(select(PassengerQRTokenModel).where(
        PassengerQRTokenModel.passenger_id == submission.id,
        PassengerQRTokenModel.agency_id == submission.agency_id,
    ).order_by(PassengerQRTokenModel.token_version.desc(), PassengerQRTokenModel.created_at.desc()).limit(1))
    qr_status: dict[str, Any] = {"status": "not_generated"}
    if token is not None:
        qr_status = {"status": "revoked" if token.revoked_at else "expired" if utc(token.expires_at) <= datetime.now(UTC)
                     else "active" if token.is_active else "inactive", "token_version": token.token_version,
                     "created_at": token.created_at, "expires_at": token.expires_at, "revoked_at": token.revoked_at}
    return PassportSubmissionResponse.model_validate({**dto.__dict__, "qr_status": qr_status})


async def document_review(group_id: UUID, document_type: str, current_user: User, session: AsyncSession) -> DocumentBatchResponse:
    from app.presentation.api.v1.routes.document_distribution_groups_read import (
        _load_document_review,
    )

    _, review = await _load_document_review(group_id, document_type, current_user=current_user,
        session=session, include_file_urls=False)
    return review


async def delivery_record(kind: Literal["document", "qr", "broadcast", "welcome"], record_id: UUID,
    current_user: User, session: AsyncSession, agency_id: UUID | None = None) -> dict[str, Any]:
    model = DELIVERY_MODELS[kind][0]
    statement = select(model).where(model.id == record_id)
    if agency_id is not None:
        statement = statement.where(model.agency_id == agency_id)
    row = await session.scalar(statement)
    if row is None:
        raise HTTPException(404, "Delivery record not found")
    await record_sensitive_read(session, user=current_user, kind="detail", agency_id=row.agency_id, entity_id=row.id)
    return {column.name: getattr(row, column.name) for column in model.__table__.columns}


def stored_columns(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


async def _broadcast(group_id: UUID, current_user: User, session: AsyncSession) -> WhatsAppBroadcastGroupModel:
    row = await session.scalar(select(WhatsAppBroadcastGroupModel).where(
        WhatsAppBroadcastGroupModel.id == group_id,
        WhatsAppBroadcastGroupModel.agency_id == current_user.agency_id))
    if row is None:
        raise HTTPException(404, "Broadcast not found")
    return row


BROADCAST_RECORD_MODELS: dict[str, Any] = {
    "recipients": WhatsAppBroadcastRecipientModel,
    "rejected_contacts": WhatsAppBroadcastRejectedContactModel,
    "source_contacts": WhatsAppBroadcastSourceContactModel,
    "support_contacts": WhatsAppBroadcastSupportContactModel,
    "group_links": ClientGroupWhatsAppBroadcastLinkModel,
    "phone_overrides": WhatsAppTravellerPhoneOverrideModel,
    "message_states": WhatsAppRecipientMessageStateModel,
}
BroadcastRecordKind = Literal["recipients", "rejected_contacts", "source_contacts", "support_contacts", "group_links", "phone_overrides", "message_states"]


async def whatsapp_broadcast_stored(group_id: UUID, current_user: User, session: AsyncSession) -> dict[str, Any]:
    broadcast = await _broadcast(group_id, current_user, session)
    counts: dict[str, int | None] = {}
    for kind, model in BROADCAST_RECORD_MODELS.items():
        counts[kind] = await session.scalar(select(func.count()).select_from(model).where(
            model.broadcast_group_id == group_id, model.agency_id == broadcast.agency_id))
    await record_sensitive_read(session, user=current_user, kind="detail",
        agency_id=broadcast.agency_id, entity_id=group_id)
    return {"broadcast": stored_columns(broadcast), "record_counts": counts,
        "record_kinds": list(BROADCAST_RECORD_MODELS), "records_view": "whatsapp_broadcast_records",
        "notice": "Stored import headings include empty columns. Recipient records include removed and merged contacts. Use whatsapp_tracking for the website's current audience and match decisions."}


async def whatsapp_broadcast_records(group_id: UUID, kind: BroadcastRecordKind,
    current_user: User, session: AsyncSession,
    offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100),
    record_id: UUID | None = None, q: str | None = Query(None, min_length=1, max_length=200),
    imported_field: str | None = Query(None, min_length=1, max_length=255),
    imported_value: str | None = Query(None, max_length=1000),
    include_removed: bool = True) -> dict[str, Any]:
    broadcast = await _broadcast(group_id, current_user, session)
    model = BROADCAST_RECORD_MODELS[kind]
    filters = [model.broadcast_group_id == group_id, model.agency_id == broadcast.agency_id]
    if record_id is not None:
        filters.append(model.id == record_id)
    if kind == "recipients" and not include_removed:
        filters.append(model.removed_at.is_(None))
    if (imported_field is None) != (imported_value is None):
        raise ValueError("Provide both imported_field and imported_value")
    if imported_field is not None:
        if not hasattr(model, "imported_fields"):
            raise ValueError("This record kind does not contain imported fields")
        filters.append(model.imported_fields[imported_field].as_string() == imported_value)
    if q:
        fields = [getattr(model, name) for name in ("name", "raw_name", "phone_number", "raw_phone_number", "normalized_phone_number", "imported_fields", "merged_contacts") if hasattr(model, name)]
        if not fields:
            raise ValueError("This record kind requires an ID filter")
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append(or_(*(cast(field, String).ilike(f"%{escaped}%", escape="\\") for field in fields)))
    statement = select(model).where(*filters).order_by(model.created_at, model.id)
    rows = list((await session.scalars(statement.offset(offset).limit(limit + 1))).all())
    total = await session.scalar(select(func.count()).select_from(model).where(*filters))
    await record_sensitive_read(session, user=current_user, kind="group_list",
        agency_id=broadcast.agency_id, entity_id=group_id, count=min(len(rows), limit))
    return {"broadcast_group_id": group_id, "agency_id": broadcast.agency_id, "kind": kind,
        "items": [stored_columns(row) for row in rows[:limit]], "total": total,
        "offset": offset, "limit": limit, "has_more": len(rows) > limit,
        "next_offset": offset + limit if len(rows) > limit else None,
        "consistency": "live_records_in_created_order; restart after audience edits"}


async def _client_group(group_id: UUID, current_user: User, session: AsyncSession) -> ClientGroupModel:
    entity = await ClientGroupRepository(session).get_by_id(group_id)
    if entity is None:
        raise HTTPException(404, "Group not found")
    await AuthorizationPolicy(session).require_view_group(current_user, entity)
    row = await session.get(ClientGroupModel, group_id)
    if row is None:
        raise HTTPException(404, "Group not found")
    return row


async def group_qr_metadata(group_id: UUID, current_user: User, session: AsyncSession) -> dict[str, Any]:
    from app.presentation.api.v1.routes.tour_operations_qr_helpers import group_passenger_qr_codes

    group = await _client_group(group_id, current_user, session)
    result = await group_passenger_qr_codes(session, group.agency_id, group,
        issue_missing=False, include_payload=False)
    # The website's generated_at is the query clock, not a saved QR field. Do
    # not invalidate a deep-read cursor on an otherwise unchanged observation.
    return result.model_dump(exclude={"generated_at"})


async def qr_delivery_eligibility(group_id: UUID, current_user: User, session: AsyncSession) -> dict[str, Any]:
    from app.presentation.api.v1.routes.tour_operations_qr_delivery import _build_preview

    group = await _client_group(group_id, current_user, session)
    result = await _build_preview(session, group=group)
    return {**result.model_dump(), "observation_notice": "Existing states are read as stored. Stale jobs are not recovered and QR codes are not issued by this read."}


async def welcome_delivery_eligibility(group_id: UUID, current_user: User, session: AsyncSession,
    source_broadcast_id: UUID | None = None) -> dict[str, Any]:
    from app.presentation.api.v1.routes.traveller_welcome_preview import (
        build_traveller_welcome_preview,
    )

    group = await _client_group(group_id, current_user, session)
    preview, _ = await build_traveller_welcome_preview(session, group=group,
        source_broadcast_id=source_broadcast_id, lock=False)
    return preview.model_dump(exclude={"preview_token"})


async def document_delivery_eligibility(group_id: UUID, document_type: str,
    current_user: User, session: AsyncSession) -> dict[str, Any]:
    from app.presentation.api.v1.routes.document_distribution_delivery import (
        preview_document_whatsapp_broadcast,
    )

    result = await preview_document_whatsapp_broadcast(group_id, document_type,
        current_user=current_user, session=session)
    return result.model_dump(exclude={"preview_token"})


async def email_activity(current_user: User, session: AsyncSession,
    offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100)) -> dict[str, Any]:
    from app.presentation.api.v1.routes.email_integration_activity import (
        email_activity as canonical_activity,
    )

    rows = await canonical_activity(current_user=current_user, session=session, offset=offset, limit=limit + 1)
    return {"items": rows[:limit], "offset": offset, "limit": limit, "has_more": len(rows) > limit,
        "next_offset": offset + limit if len(rows) > limit else None}


async def email_ai_rollout(scope_type: Literal["agency", "user", "connection"],
    current_user: User, session: AsyncSession, search: str | None = Query(None, max_length=120),
    offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100)) -> dict[str, Any]:
    from app.core.config.settings import get_settings
    from app.presentation.api.v1.routes.email_ai_rollout_admin import (
        _load_policy_map,
        _target_response,
        _target_rows,
    )

    rows = await _target_rows(session, scope_type=scope_type,
        search=" ".join((search or "").split()).casefold(), limit=limit + 1,
        offset=offset, requesting_user_id=current_user.id)
    more = len(rows) > limit
    rows = rows[:limit]
    policy_map = await _load_policy_map(session, rows)
    settings = get_settings()
    return {"scope_type": scope_type, "global_enabled": settings.email_ai_enabled,
        "global_notifications_enabled": settings.email_ai_notifications_enabled,
        "items": [_target_response(row, scope_type=scope_type, policy_map=policy_map,
            global_enabled=settings.email_ai_enabled) for row in rows],
        "offset": offset, "limit": limit, "has_more": more,
        "next_offset": offset + limit if more else None}


async def passport_image_metadata(submission_id: UUID, image_type: PassportImageType,
    current_user: User, session: AsyncSession) -> dict[str, Any]:
    from app.infrastructure.repositories.passport_image_crop_repository import (
        PassportImageCropRepository,
    )
    from app.infrastructure.repositories.passport_image_library_repository import (
        PassportImageLibraryRepository,
    )
    from app.presentation.api.v1.routes.passport_image_library import _library_item_response
    from app.presentation.api.v1.routes.passport_routes.image_support import (
        _authorized_staff_passport_image,
    )
    from app.presentation.api.v1.routes.passport_routes.response_support import _effective_crop

    submission, source_key = await _authorized_staff_passport_image(submission_id=submission_id,
        image_type=image_type, current_user=current_user, session=session, require_editor=True)
    crop = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective = _effective_crop(crop, source_storage_key=source_key)
    items = await PassportImageLibraryRepository(session).list_for_image(submission.id, image_type)
    return {"items": [_library_item_response(item=item, authoritative_source_key=source_key,
        current_edit_source_key=effective.edit_source_storage_key if effective else None) for item in items],
        "source_available": bool(source_key), "observation_notice": "Only retained library items are returned. Reading never inserts the original image into the library."}


async def _stored_ai_job(submission_id: UUID, current_user: User, session: AsyncSession,
    job_id: UUID | None = None) -> PassportVisaAiImageJobResponse | None:
    from app.infrastructure.repositories.passport_image_crop_repository import (
        PassportImageCropRepository,
    )
    from app.infrastructure.repositories.passport_visa_ai_image_job_repository import (
        PassportVisaAiImageJobRepository,
    )
    from app.presentation.api.v1.routes.passport_routes.image_support import (
        _authorized_staff_passport_image,
    )
    from app.presentation.api.v1.routes.passport_routes.response_support import _effective_crop
    from app.presentation.api.v1.routes.passport_routes.visa_ai_support import _visa_ai_job_response

    submission, source_key = await _authorized_staff_passport_image(submission_id=submission_id,
        image_type=PassportImageType.VISA_PHOTO, current_user=current_user, session=session, require_editor=True)
    repository = PassportVisaAiImageJobRepository(session)
    job = await repository.get_for_submission(submission.id, job_id) if job_id else await repository.active_for_submission(submission.id)
    if job is None:
        if job_id:
            raise HTTPException(404, "AI image job not found")
        return None
    crop = await PassportImageCropRepository(session).get(submission.id, PassportImageType.VISA_PHOTO)
    effective = _effective_crop(crop, source_storage_key=source_key)
    return await _visa_ai_job_response(submission_id=submission.id, job=job,
        current_storage_key=effective.edit_source_storage_key if effective else None, session=session)


async def passport_active_ai_image_job(submission_id: UUID, current_user: User, session: AsyncSession) -> PassportVisaAiImageJobResponse | None:
    return await _stored_ai_job(submission_id, current_user, session)


async def passport_ai_image_job(submission_id: UUID, job_id: UUID, current_user: User, session: AsyncSession) -> PassportVisaAiImageJobResponse | None:
    return await _stored_ai_job(submission_id, current_user, session, job_id)


async def delivery_receipts(kind: Literal["document", "qr", "broadcast", "welcome"], record_id: UUID,
    current_user: User, session: AsyncSession, agency_id: UUID | None = None,
    offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100)) -> dict[str, Any]:
    model = DELIVERY_MODELS[kind][0]
    query = select(model).where(model.id == record_id)
    if agency_id is not None:
        query = query.where(model.agency_id == agency_id)
    source = await session.scalar(query)
    if source is None:
        raise HTTPException(404, "Delivery record not found")
    binding_query = select(WhatsAppProviderMessageBindingModel).where(
        WhatsAppProviderMessageBindingModel.source_id == record_id,
        WhatsAppProviderMessageBindingModel.agency_id == source.agency_id,
        WhatsAppProviderMessageBindingModel.source_kind == ("traveller_welcome" if kind == "welcome" else kind))
    bindings = list((await session.scalars(binding_query)).all())
    receipt_query = select(WhatsAppProviderReceiptModel).where(
        WhatsAppProviderReceiptModel.binding_id.in_([row.id for row in bindings]))
    rows = list((await session.scalars(receipt_query.order_by(WhatsAppProviderReceiptModel.received_at,
        WhatsAppProviderReceiptModel.id).offset(offset).limit(limit + 1))).all())
    await record_sensitive_read(session, user=current_user, kind="detail",
        agency_id=source.agency_id, entity_id=record_id)
    return {"record_id": record_id, "kind": kind,
        "bindings": [stored_columns(row) for row in bindings],
        "receipts": [stored_columns(row) for row in rows[:limit]],
        "offset": offset, "limit": limit, "has_more": len(rows) > limit,
        "next_offset": offset + limit if len(rows) > limit else None,
        "notice": "Verified retained provider receipts only; reading does not poll providers or apply pending receipts."}


async def gc_common_documents(group_id: UUID, current_user: User, session: AsyncSession,
    agency_id: UUID | None = None, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100)) -> dict[str, Any]:
    from app.presentation.api.v1.routes.gc_app_content import list_common_documents

    rows = await list_common_documents(group_id, agency_id=agency_id, offset=offset,
        limit=limit + 1, current_user=current_user, session=session)
    return {"items": rows[:limit], "offset": offset, "limit": limit,
        "has_more": len(rows) > limit, "next_offset": offset + limit if len(rows) > limit else None}


async def email_reviews(current_user: User, session: AsyncSession,
    review_status: str = Query("open"), offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100)) -> dict[str, Any]:
    from app.presentation.api.v1.routes.email_integration_review_queries import list_email_reviews

    rows = await list_email_reviews(review_status=review_status, offset=offset, limit=limit + 1,
        current_user=current_user, session=session)
    return {"items": rows[:limit], "offset": offset, "limit": limit,
        "has_more": len(rows) > limit, "next_offset": offset + limit if len(rows) > limit else None}


async def email_review_options(current_user: User, session: AsyncSession,
    group_id: UUID | None = None, message_id: UUID | None = None,
    offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100)) -> dict[str, Any]:
    from app.presentation.api.v1.routes.email_integration_review_queries import (
        email_review_options as website,
    )

    result = await website(group_id=group_id, message_id=message_id, passenger_offset=offset,
        passenger_limit=limit + 1, current_user=current_user, session=session)
    data = result.model_dump(mode="json")
    rows = data["passengers"]
    data.update(passengers=rows[:limit], offset=offset, limit=limit,
        has_more=len(rows) > limit, next_offset=offset + limit if len(rows) > limit else None)
    return data
