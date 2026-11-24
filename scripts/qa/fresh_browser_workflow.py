"""Fresh-flow qualification: capture only delivery, inspect actual publication.

This helper is mounted solely in the disposable qualification stack. It never
creates a verified proof or submission; those transitions use the real HTTP API.
"""
from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import func, select

from app.application.travellers.draft_store import FreshDraftStore
from app.application.travellers.fresh_contact import request_fresh_code
from app.application.travellers.fresh_drafts import fresh_secret, require_fresh_draft
from app.core.config.settings import get_settings
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.public_upload_contact_model import (
    PublicUploadContactChallengeModel,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftContactProofModel as Proof,
)
from app.infrastructure.security.public_upload_otp_rate_limiter import (
    PublicUploadOTPRateLimiter,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.schemas.public_upload_contact_schemas import (
    PublicContactOTPRequest,
)

BROWSER_TOKENS = {f"enterprise-browser-public-{name}-qa" for name in ("chromium", "firefox", "webkit")}


def qualification_secret(service: FreshDraftStore, body: dict[str, str]) -> str:
    if get_settings().database.db != "passdetection_ci_browser":
        raise RuntimeError("Only the disposable passdetection_ci_browser database is allowed")
    if body["group_token"] not in BROWSER_TOKENS:
        raise RuntimeError("Only the dedicated browser upload groups are allowed")
    return fresh_secret(service, body["group_token"], body["browser_secret"], body["session_id"])


class CapturedDelivery:
    code: str | None = None

    async def send_code(self, *, normalized_phone: str, code: str, expires_in_seconds: int) -> str:
        self.code = code
        return "isolated-browser-delivery"


async def request_contact(service: FreshDraftStore, body: dict[str, str]) -> dict[str, object]:
    secret = qualification_secret(service, body)
    contact = PublicContactOTPRequest.model_validate({key: body[key] for key in ("group_token", "email", "phone_number")})
    delivery = CapturedDelivery()
    challenge, expires, resend = await request_fresh_code(service, contact.group_token, secret,
        email=str(contact.email), phone=contact.phone_number, ip_address="127.0.0.1",
        provider=delivery, limiter=PublicUploadOTPRateLimiter())
    if delivery.code is None:
        raise RuntimeError("A new qualification challenge did not deliver a code")
    return {"response": {"challenge_id": str(challenge), "expires_in_seconds": expires,
        "resend_after_seconds": resend}, "delivered_code": delivery.code}


async def inspect_publication(service: FreshDraftStore, body: dict[str, str]) -> dict[str, object]:
    secret = qualification_secret(service, body)
    draft = await require_fresh_draft(service, body["group_token"], secret, submitted=True)
    if draft.status != "submitted" or draft.source_submission_id != uuid.UUID(body["source_submission_id"]):
        raise RuntimeError("The requested source is not this submitted draft's result")
    source = await service.session.get(PassportSubmissionModel, draft.source_submission_id)
    if source is None or (source.agency_id, source.group_id) != (draft.agency_id, draft.group_id):
        raise RuntimeError("Published source scope does not match its draft")
    proof = await service.session.scalar(select(Proof).where(Proof.draft_id == draft.id, Proof.agency_id == draft.agency_id))
    published = await service.session.get(PublicUploadContactChallengeModel, source.id)
    assets = list(await service.session.scalars(select(Asset).where(Asset.draft_id == draft.id,
        Asset.agency_id == draft.agency_id, Asset.is_current.is_(True))))
    storage = MinioStorageRepository()
    documents = []
    for asset in assets:
        field = {"cover": "passport_cover_s3_key", "back_cover": "passport_back_cover_s3_key"}.get(asset.side)
        if field is None:
            raise RuntimeError("The cover-only qualification received an unexpected document")
        key = getattr(source, field)
        if not key or key != asset.object_key or asset.state != "adopted":
            raise RuntimeError("A published document was not adopted from this draft")
        content = await storage.get_file(key)
        documents.append({"id": str(asset.id), "side": asset.side, "state": asset.state,
            "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(),
            "checksum_matches": hashlib.sha256(content).hexdigest() == asset.checksum,
            "legacy_temporary_key": key.startswith("drafts/")})
    count = await service.session.scalar(select(func.count()).select_from(PassportSubmissionModel).where(
        PassportSubmissionModel.group_id == draft.group_id,
        PassportSubmissionModel.upload_idempotency_key == body["session_id"]))
    return {"source_submission_id": str(source.id), "source_status": source.status,
        "source_count": count, "reviewed": source.client_reviewed_at is not None,
        "upload_session_bound": source.upload_idempotency_key == body["session_id"],
        "draft_status": draft.status, "draft_proof_status": proof.status if proof else None,
        "published_proof_status": published.status if published else None,
        "same_proof": bool(proof and published and proof.id == published.id), "documents": documents}
