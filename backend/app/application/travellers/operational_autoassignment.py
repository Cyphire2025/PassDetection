"""Publish an operator-authorized roster match without waiting for a link visit.

Constant-sized indexed lookups and at most 16 asset metadata rows per match.
The reconciliation caller owns commit/checkpoint. Group/person row locks and
the existing unique group-person constraint serialize retries and public reuse.
No OCR, file download, broadcast mutation or old-trip update occurs here.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.asset_policy import is_reviewable_asset
from app.application.travellers.authority import accepted_document
from app.application.travellers.errors import ReuseError
from app.application.travellers.history import PASSPORT_REVIEW_FIELDS, question_version
from app.application.travellers.requirements import (
    missing_document_requirements,
    requirement_signatures,
)
from app.application.travellers.retained_authority import has_retained_authority
from app.application.travellers.submission_snapshot import new_reuse_submission
from app.domain.services.traveller_suitability import (
    SuitabilityOutcome,
    TravelDocument,
    assess_document,
)
from app.domain.services.traveller_verification import utc
from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerChangeEventModel,
    TravellerContactBindingModel,
    TravellerDocumentAssetModel,
    TravellerParticipationModel,
    TravellerPassportModel,
    TravellerProfileModel,
    TravellerReusePolicyModel,
)
from app.infrastructure.repositories.platform_policy_repository import PlatformPolicyRepository
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto

AssignmentOutcome = Literal["assigned", "replacement_required", "unavailable", "assets_pending"]


async def assign_operational_traveller(session: AsyncSession, *, group: ClientGroupModel,
    person_id: uuid.UUID, source_kind: str, source_row_key: str, evidence: dict[str, object],
    crypto: TravellerReuseCrypto, now: datetime,
) -> AssignmentOutcome:
    if source_kind not in {"whatsapp_recipient", "whatsapp_rejected"} or len(source_row_key) > 128:
        return "unavailable"
    locked = await session.scalar(select(ClientGroupModel).where(ClientGroupModel.id == group.id,
        ClientGroupModel.agency_id == group.agency_id).with_for_update().execution_options(populate_existing=True))
    if locked is None or locked.company_id is None or locked.status != "active" or locked.deleted_at is not None or locked.import_only:
        return "unavailable"
    group = locked
    company_id = group.company_id
    assert company_id is not None
    company = await session.scalar(select(ClientOrganizationModel).where(
        ClientOrganizationModel.id == group.company_id, ClientOrganizationModel.agency_id == group.agency_id,
        ClientOrganizationModel.status == "active").with_for_update(read=True))
    policy = await session.scalar(select(TravellerReusePolicyModel).where(
        TravellerReusePolicyModel.company_id == group.company_id, TravellerReusePolicyModel.agency_id == group.agency_id,
        TravellerReusePolicyModel.enabled.is_(True)).with_for_update(read=True))
    if company is None or policy is None:
        return "unavailable"
    person = await session.scalar(select(TravellerProfileModel).where(
        TravellerProfileModel.id == person_id, TravellerProfileModel.agency_id == group.agency_id,
        TravellerProfileModel.company_id == group.company_id, TravellerProfileModel.status == "active",
        TravellerProfileModel.deleted_at.is_(None), TravellerProfileModel.reuse_permission_status != "withdrawn",
    ).with_for_update().execution_options(populate_existing=True))
    if person is None or not has_retained_authority(person) or (person.retention_until is not None and utc(person.retention_until) <= now):
        return "unavailable"
    participation = await session.scalar(select(TravellerParticipationModel).where(
        TravellerParticipationModel.agency_id == group.agency_id,
        TravellerParticipationModel.company_id == group.company_id,
        TravellerParticipationModel.group_id == group.id, TravellerParticipationModel.traveller_id == person.id,
    ).with_for_update().execution_options(populate_existing=True))
    if participation is not None:
        if participation.status == "withdrawn":
            return "unavailable"
        if participation.source_submission_id is not None:
            # Never replace any existing trip source or reapply a changed current
            # document onto a frozen snapshot when this job is retried.
            return "assigned" if participation.status in {"accepted", "submitted"} else "unavailable"
    passport_id = await session.scalar(select(TravellerPassportModel.id).where(
        TravellerPassportModel.agency_id == group.agency_id, TravellerPassportModel.company_id == group.company_id,
        TravellerPassportModel.traveller_id == person.id, TravellerPassportModel.status == "accepted",
        TravellerPassportModel.is_default.is_(True)))
    if passport_id is None:
        await _invite_for_replacement(session, group, person, participation, source_row_key)
        return "replacement_required"
    try:
        passport, revision = await accepted_document(session, agency_id=group.agency_id,
            company_id=company_id, traveller_id=person.id, passport_id=passport_id, crypto=crypto)
    except ReuseError:
        await _invite_for_replacement(session, group, person, participation, source_row_key)
        return "replacement_required"
    raw = json.loads(crypto.decrypt(revision.fields_ciphertext))
    if not isinstance(raw, dict):
        return "unavailable"
    fields = {key: value for key, value in raw.items() if key in PASSPORT_REVIEW_FIELDS and isinstance(value, str)}
    assets = list(await session.scalars(select(TravellerDocumentAssetModel).where(
        TravellerDocumentAssetModel.agency_id == group.agency_id,
        TravellerDocumentAssetModel.company_id == group.company_id,
        TravellerDocumentAssetModel.traveller_id == person.id,
        TravellerDocumentAssetModel.document_revision_id == revision.id,
        TravellerDocumentAssetModel.kind == "original",
    ).order_by(TravellerDocumentAssetModel.id).limit(16)))
    if any(asset.availability == "pending" for asset in assets):
        return "assets_pending"
    sides = {asset.document_side for asset in assets if is_reviewable_asset(asset, now)}
    suitability = assess_document(TravelDocument(issuing_country=passport.issuing_country,
        nationality=fields.get("nationality"), document_type=passport.document_type,
        issue_date=revision.issue_date, expiry_date=revision.expiry_date, accepted=True,
        available="front" in sides, lifecycle=passport.status), travel_date=group.travel_date,
        today=now.date(), destinations=(group.destination,) if group.destination else (), rules=())
    if suitability.outcome in {SuitabilityOutcome.REPLACEMENT_REQUIRED, SuitabilityOutcome.CANNOT_ASSESS}:
        await _invite_for_replacement(session, group, person, participation, source_row_key)
        return "replacement_required"
    contact_rows = (await session.execute(select(TravellerContactBindingModel.kind,
        TravellerContactBindingModel.value_ciphertext).where(
        TravellerContactBindingModel.agency_id == group.agency_id,
        TravellerContactBindingModel.company_id == group.company_id,
        TravellerContactBindingModel.traveller_id == person.id,
        TravellerContactBindingModel.status == "current",
        TravellerContactBindingModel.kind.in_(("phone", "email")),
    ).limit(2))).all()
    contacts = {kind: crypto.decrypt(value) for kind, value in contact_rows}
    policies = await PlatformPolicyRepository(session).load()
    version = question_version(group, policies)
    key = "auto:" + hashlib.sha256(f"{group.id}:{person.id}".encode()).hexdigest()
    if participation is None:
        participation = _pending_membership(group, person, source_row_key, version)
        session.add(participation)
    source = new_reuse_submission(group=group, person=person, revision=revision, assets=assets, fields=fields,
        display_name=crypto.decrypt(person.display_name_ciphertext) if person.display_name_ciphertext else "Traveller",
        phone=contacts.get("phone"), email=contacts.get("email"), participation_id=participation.id,
        now=now, traveller_confirmed=False)
    missing = missing_document_requirements(group, sides)
    source.staff_metadata = {**(source.staff_metadata or {}), "reuse_source_kind": source_kind,
        "reuse_source_row_key": source_row_key, "reuse_missing_requirements": json.dumps(missing)}
    session.add(source)
    await session.flush()
    participation.source_submission_id = source.id
    participation.passport_id, participation.document_revision_id = passport.id, revision.id
    participation.profile_revision, participation.contact_revision = person.revision, person.contact_revision
    participation.question_version, participation.trip_started_at = version, group.travel_date
    participation.answers = {"custom_answers": [], "custom_detail_answers": [], "current_details": {}}
    participation.confirmations = {"information_confirmed": False, "assignment_mode": "automatic",
        "operator_policy_revision": policy.revision, "match_evidence": evidence,
        "requirement_signatures": requirement_signatures(group, policies),
        "assigned_at": now.isoformat(), "suitability": {"outcome": suitability.outcome.value,
            "reason_codes": list(suitability.reason_codes)}}
    participation.status, participation.revision = "accepted", participation.revision + 1
    participation.accepted_at = now
    session.add(TravellerChangeEventModel(id=uuid.uuid4(), agency_id=group.agency_id,
        company_id=group.company_id, traveller_id=person.id, event_type="added",
        aggregate_id=participation.id, aggregate_revision=participation.revision,
        idempotency_key=key, reason_code="operator_roster_autoassignment"))
    await session.flush()
    return "assigned"


def _pending_membership(group: ClientGroupModel, person: TravellerProfileModel,
    source_row_key: str, version: str,
) -> TravellerParticipationModel:
    return TravellerParticipationModel(id=uuid.uuid4(), agency_id=group.agency_id,
        company_id=group.company_id, group_id=group.id, traveller_id=person.id,
        source_kind="reviewed_roster", source_row_key=source_row_key,
        idempotency_key="auto:" + hashlib.sha256(f"{group.id}:{person.id}".encode()).hexdigest(),
        revision=1, profile_revision=person.revision, contact_revision=person.contact_revision,
        question_version=version, status="pending", confirmations={}, answers={})


async def _invite_for_replacement(session: AsyncSession, group: ClientGroupModel,
    person: TravellerProfileModel, participation: TravellerParticipationModel | None,
    source_row_key: str,
) -> None:
    # Exact roster eligibility permits the verification flow, never document
    # disclosure by itself. An unsuitable passport produces no accepted trip.
    if participation is None:
        policies = await PlatformPolicyRepository(session).load()
        participation = _pending_membership(group, person, source_row_key, question_version(group, policies))
        participation.confirmations = {"information_confirmed": False,
            "assignment_mode": "replacement_required"}
        session.add(participation)
        await session.flush()
