"""Bounded historical replay keys follow the immutable proof used for acceptance."""

import json
import uuid

from app.application.travellers.accepted_source import accept_source, retained_source_is_current
from app.application.travellers.legacy_source_acceptance import AI_ACCEPTANCE_RULE
from app.application.travellers.source_acceptance_provenance import acceptance_provenance
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import TravellerDocumentRevisionModel
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto


def registration_is_current(document: TravellerDocumentRevisionModel | None,
    source: PassportSubmissionModel, crypto: TravellerReuseCrypto,
) -> bool:
    if document is None:
        return False
    if source.status != "ai_approved":
        return True
    return (document.source_provenance.get("acceptance_rule") == AI_ACCEPTANCE_RULE
        and retained_source_is_current(document, source, crypto))


def historical_enrollment_key(source: PassportSubmissionModel, company_id: uuid.UUID,
    crypto: TravellerReuseCrypto,
) -> str:
    if source.status != "ai_approved":
        return f"history:{source.id}:{source.extraction_revision}"
    accepted = accept_source(source, dict(source.confirmed_fields or {}), operator=True)
    proof = acceptance_provenance(accepted, source, crypto)
    generation = crypto.scoped_digest("historical-ai-generation", source.agency_id, company_id,
        str(source.extraction_revision), json.dumps(proof, sort_keys=True, separators=(",", ":")))
    return f"history-ai:{source.id}:{generation}"
