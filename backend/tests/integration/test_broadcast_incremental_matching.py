"""A later shared-import call wakes an already completed linked roster job."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import func, select

from app.application.travellers.identity_index import replace_identity_evidence
from app.application.travellers.reconciliation import reconcile_page
from app.domain.entities.entities import UserRole
from app.domain.services.traveller_identity import identity_evidence
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    UserModel,
    WhatsAppBroadcastGroupModel,
)
from app.infrastructure.database.traveller_reuse_models import TravellerParticipationModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerReconciliationJobModel as Job,
)
from app.presentation.api.v1.routes import whatsapp_recipient_additions as additions
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppRecipientInput
from tests.integration.traveller_reuse_fixtures import reuse_context, seed_person


async def test_second_import_assigns_new_person_without_relink_and_preserves_first_snapshot(db_session, test_settings, monkeypatch):
    service, _, target = await reuse_context(db_session, test_settings)
    actor = UserModel(agency_id=target.agency_id, email=f"{uuid.uuid4()}@example.invalid",
        full_name="Synthetic importer", hashed_password="unused", role="agency_admin")
    broadcast = WhatsAppBroadcastGroupModel(agency_id=target.agency_id, name="Synthetic import")
    db_session.add_all([actor, broadcast])
    await db_session.flush()
    db_session.add(ClientGroupWhatsAppBroadcastLinkModel(agency_id=target.agency_id,
        client_group_id=target.id, broadcast_group_id=broadcast.id))
    await db_session.flush()
    user = SimpleNamespace(id=actor.id, agency_id=actor.agency_id, role=UserRole.AGENCY_ADMIN)
    monkeypatch.setattr(additions, "_group_detail", AsyncMock(return_value="saved"))
    monkeypatch.setattr(additions, "reconcile_mobile_passenger_access_for_broadcast", AsyncMock())
    first_source_id = None
    for index in (1, 2):
        person = await seed_person(service, target, index, phone=f"+91987654321{index}")
        name = f"Synthetic{index} Surname{index}"
        fields = {"name": name, "passport_number": person.number, "date_of_birth": "1990-02-03"}
        await replace_identity_evidence(db_session, person=person.profile,
            evidence=identity_evidence(fields, name=name, phone=person.phone), crypto=service.crypto,
            source={"kind": "synthetic_test"})
        assert await additions.add_validated_broadcast_recipients(group_id=broadcast.id,
            contacts=[WhatsAppRecipientInput(name=name, phone_number=person.phone, imported_fields=fields)],
            rejected_contacts=[], declared_field_keys=list(fields), recipient_opt_in_confirmed=True,
            current_user=user, session=db_session) == "saved"
        job = await db_session.scalar(select(Job))
        assert job.status == "queued"
        await reconcile_page(db_session, job_id=job.id, crypto=service.crypto)
        assert job.status == "succeeded"
        assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == index
        members = list(await db_session.scalars(select(TravellerParticipationModel).order_by(TravellerParticipationModel.created_at)))
        assert all(member.confirmations["assignment_mode"] == "automatic" for member in members)
        if first_source_id is None:
            first_source_id = members[0].source_submission_id
        else:
            assert members[0].source_submission_id == first_source_id
        assert await db_session.scalar(select(func.count()).select_from(Job)) == 1
