"""Synthetic encrypted travellers and fake OTP delivery; never sends externally."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from cryptography.fernet import Fernet

from app.application.travellers.claims import ReturningClaims
from app.core.config.traveller_reuse import TravellerReuseSettings
from app.infrastructure.database.traveller_reuse_models import (
    TravellerContactBindingModel,
    TravellerDocumentAssetModel,
    TravellerDocumentRevisionModel,
    TravellerGroupReuseConfigModel,
    TravellerIdentifierModel,
    TravellerPassportModel,
    TravellerProfileModel,
    TravellerReusePolicyModel,
)
from tests.unit.application.test_traveller_reconciliation import _seed_scope


@dataclass
class SyntheticPerson:
    profile: TravellerProfileModel
    passport: TravellerPassportModel
    document: TravellerDocumentRevisionModel
    asset: TravellerDocumentAssetModel
    phone: str
    code: str
    number: str


async def reuse_context(session, settings):
    agency, company, group = await _seed_scope(session)
    group.travel_date = date.today() + timedelta(days=90)
    group.destination = "Local operational test"
    reuse = TravellerReuseSettings(disclosure_enabled=True, lookup_key="synthetic-lookup-key-" * 3,
                                    encryption_key=Fernet.generate_key().decode(), key_version="synthetic-v1")
    service = ReturningClaims(session, settings, reuse)
    session.add(TravellerReusePolicyModel(
        agency_id=agency.id, company_id=company.id, enabled=True, retention_mode="until_withdrawn",
        purpose_version="test-purpose-v1", notice_version="test-notice-v1", processing_basis="synthetic-permission",
        configured_at=datetime.now(UTC),
    ))
    session.add(TravellerGroupReuseConfigModel(agency_id=agency.id, company_id=company.id, group_id=group.id,
                                               roster_mode="open", individual_identifier_type="employee"))
    await session.flush()
    return service, company, group


async def seed_person(service, group, index=1, *, phone="+919876543210", verified=True, reliable=True):
    session, crypto = service.session, service.crypto
    now = datetime.now(UTC)
    number, code = f"00P{index:06d}", f"00E{index:06d}"
    profile = TravellerProfileModel(id=uuid.uuid4(), agency_id=group.agency_id, company_id=group.company_id,
        status="active", display_name_ciphertext=crypto.encrypt(f"Synthetic{index} Surname{index}"),
        reuse_permission_status="granted", reuse_permission_evidence={"notice": "test-notice-v1", "consent": "synthetic"})
    session.add(profile)
    await session.flush()
    passport = TravellerPassportModel(id=uuid.uuid4(), agency_id=group.agency_id, company_id=group.company_id,
        traveller_id=profile.id, issuing_country="IND", document_type="P", status="accepted", is_default=True,
        number_fingerprint=crypto.passport_fingerprint(group.agency_id, group.company_id, number, "IND", "P"),
        fingerprint_key_version=crypto.key_version, number_ciphertext=crypto.encrypt(number))
    session.add(passport)
    await session.flush()
    fields = {"given_names": f"Synthetic{index}", "surname": f"Surname{index}", "passport_number": number,
              "nationality": "IND", "unapproved_internal_field": "MUST-NOT-LEAK", "s3_key": "private-secret"}
    provenance = {key: {"accepted": True, "source": "staff_review"} for key in ("date_of_birth", "issue_date", "expiry_date")} if reliable else {}
    document = TravellerDocumentRevisionModel(id=uuid.uuid4(), agency_id=group.agency_id, company_id=group.company_id,
        traveller_id=profile.id, passport_id=passport.id, status="accepted", revision_number=1,
        fields_ciphertext=crypto.encrypt(json.dumps(fields)), date_of_birth=date(1990, 2, 3),
        issue_date=date(2024, 4, 5), expiry_date=date(2035, 4, 4), reliable_fields=provenance,
        source_provenance={"kind": "synthetic-staff-review"}, accepted_at=now, idempotency_key=uuid.uuid4().hex)
    session.add(document)
    await session.flush()
    asset = TravellerDocumentAssetModel(id=uuid.uuid4(), agency_id=group.agency_id, company_id=group.company_id,
        traveller_id=profile.id, passport_id=passport.id, document_revision_id=document.id, kind="original",
        document_side="front", object_key=f"test-only/{uuid.uuid4()}.png", content_type="image/png",
        byte_size=10, availability="available", retention_basis="synthetic-consent")
    session.add_all([asset, TravellerContactBindingModel(agency_id=group.agency_id, company_id=group.company_id,
        traveller_id=profile.id, kind="phone", status="current", value_ciphertext=crypto.encrypt(phone),
        value_fingerprint=crypto.scoped_digest("phone", group.agency_id, group.company_id, phone),
        fingerprint_key_version=crypto.key_version, verified_at=now if verified else None,
        verification_evidence={"method": "whatsapp_otp"} if verified else {}, is_shared=True),
        TravellerIdentifierModel(agency_id=group.agency_id, company_id=group.company_id, traveller_id=profile.id,
            identifier_type="employee", value_ciphertext=crypto.encrypt(code),
            value_fingerprint=crypto.scoped_digest("identifier", group.agency_id, group.company_id, "employee", code),
            fingerprint_key_version=crypto.key_version, is_individual=True)])
    await session.flush()
    return SyntheticPerson(profile, passport, document, asset, phone, code, number)


class FakeOTP:
    code = ""
    calls = 0

    async def send_code(self, *, normalized_phone, code, expires_in_seconds):
        self.code = code
        self.calls += 1


class FakeLimiter:
    async def consume(self, **kwargs):
        pass
