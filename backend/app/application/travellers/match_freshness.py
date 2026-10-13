"""Revalidate one scoped source before human-reviewed roster inclusion."""

import hmac
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.reconciliation_sources import current_source, source_fingerprint
from app.domain.exceptions.exceptions import ConflictError
from app.infrastructure.database.traveller_reuse_models import (
    TravellerGroupReuseConfigModel,
    TravellerMatchCaseModel,
    TravellerReusePolicyModel,
)
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto


async def require_fresh_match(session: AsyncSession, *, case: TravellerMatchCaseModel,
    group_revision: int, crypto: TravellerReuseCrypto,
) -> None:
    evidence = case.evidence or {}
    valid_kind = case.source_kind in {"passport_submission", "whatsapp_recipient", "whatsapp_rejected"}
    if (not valid_kind or case.reason_code == "authorized_replacement_candidate"
            or evidence.get("decision_version") not in {3, 4} or evidence.get("group_revision") != group_revision
            or evidence.get("fingerprint_key_version") != crypto.key_version):
        raise ConflictError("The source or matching rules changed. Run a new matching preview.")
    if evidence.get("decision_version") == 4:
        policy = await session.scalar(select(TravellerReusePolicyModel).where(
            TravellerReusePolicyModel.agency_id == case.agency_id,
            TravellerReusePolicyModel.company_id == case.company_id))
        if policy is None or not policy.enabled or policy.revision != evidence.get("policy_revision"):
            raise ConflictError("The matching policy changed. Run a new matching preview.")
    else:
        config = await session.scalar(select(TravellerGroupReuseConfigModel).where(
            TravellerGroupReuseConfigModel.group_id == case.group_id,
            TravellerGroupReuseConfigModel.agency_id == case.agency_id,
            TravellerGroupReuseConfigModel.company_id == case.company_id,
        ))
        if (evidence.get("config_revision") != (config.revision if config else None)
                or evidence.get("identifier_type") != (config.individual_identifier_type if config else None)):
            raise ConflictError("The identifier rules changed. Run a new matching preview.")
    try:
        identifier = uuid.UUID(case.source_row_key)
    except (ValueError, TypeError) as exc:
        raise ConflictError("The matching source is unavailable. Run a new matching preview.") from exc
    source = await current_source(session, agency_id=case.agency_id, group_id=case.group_id,
        kind=case.source_kind, identifier=identifier)
    stored_fingerprint = evidence.get("source_fingerprint")
    if (source is None or source.extraction_revision != evidence.get("source_revision")
            or not isinstance(stored_fingerprint, str)
            or not hmac.compare_digest(stored_fingerprint, source_fingerprint(crypto, case.agency_id, case.company_id, source))):
        raise ConflictError("The source changed or was removed. Run a new matching preview.")
