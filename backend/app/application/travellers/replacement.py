"""Link a privately authorized fresh upload to a reviewed replacement candidate.

This grants no retained-document status or new history access. Staff must review
the new source and explicitly enroll it. All queries seek one scoped record.
"""

from __future__ import annotations

import hmac
import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select

from app.application.travellers.claims import ReturningClaims
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.history import review_context, review_version
from app.application.travellers.source_evidence import source_evidence_digest
from app.core.security.upload_session import upload_session_matches_identifier
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import TravellerMatchCaseModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.platform_policy_repository import PlatformPolicyRepository


async def link_replacement_candidate(
    service: ReturningClaims, token: str, *, source_submission_id: uuid.UUID,
    upload_session_id: str, expected_extraction_revision: int, expected_review_version: str,
    change_kind: Literal["renewal", "scan", "correction"], idempotency_key: str,
) -> uuid.UUID:
    context = await review_context(service, token)
    grant, scope, person, _, _, _ = context
    if "participation:submit" not in grant.allowed_actions:
        raise ReuseError(ReuseReason.UNAVAILABLE)
    policies = await PlatformPolicyRepository(service.session).load()
    if not hmac.compare_digest(expected_review_version, review_version(service, context, policies)):
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    source = await service.session.scalar(select(PassportSubmissionModel).where(
        PassportSubmissionModel.id == source_submission_id,
        PassportSubmissionModel.agency_id == grant.agency_id,
        PassportSubmissionModel.group_id == grant.group_id,
    ).with_for_update())
    if source is None or not upload_session_matches_identifier(upload_session_id, source.upload_idempotency_key or ""):
        raise ReuseError(ReuseReason.UNAVAILABLE)
    if source.extraction_revision != expected_extraction_revision:
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    if source.status not in {"client_submitted", "submitted", "ai_approved", "needs_review", "staff_approved", "confirmed"} or source.client_reviewed_at is None:
        raise ReuseError(ReuseReason.INSUFFICIENT_EVIDENCE)
    case = await service.session.scalar(select(TravellerMatchCaseModel).where(
        TravellerMatchCaseModel.agency_id == grant.agency_id,
        TravellerMatchCaseModel.company_id == grant.company_id,
        TravellerMatchCaseModel.group_id == grant.group_id,
        TravellerMatchCaseModel.source_kind == "passport_submission",
        TravellerMatchCaseModel.source_row_key == str(source.id),
    ).with_for_update())
    if case is not None and case.reason_code == "authorized_replacement_candidate" and case.evidence.get("idempotency_key") == idempotency_key:
        if (case.traveller_id != person.id or case.evidence.get("idempotency_key") != idempotency_key
                or case.evidence.get("change_kind") != change_kind
                or case.evidence.get("source_extraction_revision") != expected_extraction_revision):
            raise ReuseError(ReuseReason.REVISION_CONFLICT)
        return case.id
    if case is not None and (case.status in {"conflicting", "ambiguous", "resolved", "purged"}
            or (case.traveller_id is not None and case.traveller_id != person.id)):
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    if case is None:
        case = TravellerMatchCaseModel(id=uuid.uuid4(), agency_id=grant.agency_id, company_id=grant.company_id,
            group_id=grant.group_id, source_kind="passport_submission", source_row_key=str(source.id), revision=1)
        service.session.add(case)
    else:
        case.revision += 1
    case.status, case.reason_code, case.traveller_id = "provisional", "authorized_replacement_candidate", person.id
    case.evidence = {"grant_id": str(grant.id), "actor_kind": grant.actor_kind,
        "profile_revision": person.revision, "authorization_version": person.authorization_version,
        "source_extraction_revision": source.extraction_revision, "change_kind": change_kind,
        "group_revision": scope.group.company_revision, "company_revision": scope.company.revision,
        "idempotency_key": idempotency_key, "linked_at": datetime.now(UTC).isoformat(),
        "source_evidence_digest": source_evidence_digest(service.crypto, source),
        "fingerprint_key_version": service.crypto.key_version}
    await AuditLogRepository(service.session).record(action="traveller.replacement_candidate_linked",
        entity_type="traveller_match_case", entity_id=str(case.id), agency_id=grant.agency_id,
        metadata={"grant_id": str(grant.id), "source_submission_id": str(source.id), "change_kind": change_kind})
    await service.session.flush()
    return case.id
