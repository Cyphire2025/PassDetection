"""Freeze and recheck the authority used to accept one immutable source revision."""

import hmac

from app.application.travellers import legacy_staff_acceptance as staff
from app.application.travellers.accepted_source import (
    MRZ_ACCEPTANCE_RULE,
    STAFF_ACCEPTED_STATUSES,
    AcceptedSource,
    accept_source,
)
from app.application.travellers.legacy_source_acceptance import AI_ACCEPTANCE_RULE
from app.application.travellers.source_evidence import source_evidence_digest
from app.application.travellers.versioning import EnrollmentError
from app.core.config.traveller_reuse import get_traveller_reuse_settings
from app.domain.services.traveller_verification import UNKNOWN_ISSUING_COUNTRY, utc
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import TravellerDocumentRevisionModel
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto


def acceptance_provenance(accepted: AcceptedSource, source: PassportSubmissionModel,
    crypto: TravellerReuseCrypto,
) -> dict[str, object]:
    context = "validated_saved_mrz" if accepted.mrz_context else "reviewed_fields"
    if accepted.fields.get("issuing_country") == UNKNOWN_ISSUING_COUNTRY:
        context = "not_recorded"
    result: dict[str, object] = {"acceptance_rule": accepted.acceptance_rule, "issuing_context_source": context}
    if accepted.acceptance_rule == staff.STAFF_ACCEPTANCE_RULE:
        result.update(staff.staff_acceptance_proof(source, crypto))
    if accepted.acceptance_rule == AI_ACCEPTANCE_RULE:
        assert source.post_submission_verified_at is not None
        result.update(source_verification_revision=source.post_submission_verification_revision,
            source_verified_at=utc(source.post_submission_verified_at).isoformat(),
            source_input_digest=source_evidence_digest(crypto, source))
    return result


def source_is_current(revision: TravellerDocumentRevisionModel, source: PassportSubmissionModel,
    crypto: TravellerReuseCrypto | None,
) -> bool:
    if revision.source_provenance.get("acceptance_rule") == staff.STAFF_ACCEPTANCE_RULE:
        return staff.staff_source_is_current(revision, source, crypto)
    if revision.source_provenance.get("acceptance_rule") != AI_ACCEPTANCE_RULE:
        if source.status in STAFF_ACCEPTED_STATUSES:
            return True
        if revision.source_provenance.get("acceptance_rule") != MRZ_ACCEPTANCE_RULE:
            return False
        try:
            return accept_source(source, dict(source.confirmed_fields or {}), operator=True).reliable_source == "verified_import"
        except EnrollmentError:
            return False
    try:
        accepted = accept_source(source, dict(source.confirmed_fields or {}), operator=True)
    except EnrollmentError:
        return False
    if accepted.acceptance_rule != AI_ACCEPTANCE_RULE or source.post_submission_verified_at is None:
        return False
    crypto = crypto or TravellerReuseCrypto(get_traveller_reuse_settings())
    provenance = revision.source_provenance
    return bool(provenance.get("source_verification_revision") == source.post_submission_verification_revision
        and provenance.get("source_verified_at") == utc(source.post_submission_verified_at).isoformat()
        and hmac.compare_digest(str(provenance.get("source_input_digest", "")), source_evidence_digest(crypto, source)))
