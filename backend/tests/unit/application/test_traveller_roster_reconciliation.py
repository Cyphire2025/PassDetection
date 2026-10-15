"""Every durably saved imported person is recognized before phone delivery."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.application.travellers.match_freshness import require_fresh_match
from app.application.travellers.reconciliation import enqueue_reconciliation, reconcile_page
from app.domain.exceptions.exceptions import ConflictError
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerGroupReuseConfigModel,
    TravellerIdentifierModel,
    TravellerMatchCaseModel,
    TravellerParticipationModel,
)
from tests.unit.application.test_traveller_reconciliation import _crypto, _seed_people, _seed_scope


@pytest.mark.asyncio
async def test_700_durable_people_one_delivery_phone_remain_700_match_cases(db_session):
    _, _, group = await _seed_scope(db_session)
    crypto = _crypto()
    people = await _seed_people(db_session, group, 400, crypto)
    db_session.add(TravellerGroupReuseConfigModel(agency_id=group.agency_id, company_id=group.company_id,
        group_id=group.id, individual_identifier_type="staff_code"))
    db_session.add_all([TravellerIdentifierModel(agency_id=group.agency_id, company_id=group.company_id,
        traveller_id=person.id, identifier_type="staff_code", value_ciphertext=crypto.encrypt(f"00E{index:04d}"),
        value_fingerprint=crypto.scoped_digest("identifier", group.agency_id, group.company_id, "staff_code", f"00E{index:04d}"),
        fingerprint_key_version=crypto.key_version, is_individual=True) for index, person in enumerate(people)])
    broadcast = WhatsAppBroadcastGroupModel(agency_id=group.agency_id, name="Saved imported roster")
    unrelated = WhatsAppBroadcastGroupModel(agency_id=group.agency_id, name="Unlinked roster")
    db_session.add_all([broadcast, unrelated])
    await db_session.flush()
    db_session.add(ClientGroupWhatsAppBroadcastLinkModel(agency_id=group.agency_id,
        client_group_id=group.id, broadcast_group_id=broadcast.id))
    recipient = WhatsAppBroadcastRecipientModel(agency_id=group.agency_id, broadcast_group_id=broadcast.id,
        name="Person 0", phone_number="+919999999999", normalized_phone_number="+919999999999",
        imported_fields={"staff_code": "00E0000", "staff_code_2": "00E0001"})
    db_session.add_all([recipient, WhatsAppBroadcastRecipientModel(agency_id=group.agency_id,
        broadcast_group_id=unrelated.id, name="Unlinked", phone_number="+919999999999",
        normalized_phone_number="+919999999999", imported_fields={"staff_code": "00E0000"})])
    db_session.add_all([WhatsAppBroadcastRejectedContactModel(agency_id=group.agency_id,
        broadcast_group_id=broadcast.id, source_file_name="synthetic.xlsx", sheet_name="People", row_number=index + 2,
        raw_name=f"Person {index}", raw_phone_number="+919999999999", imported_fields={"staff_code": f"00E{index:04d}"},
        reason_code="duplicate_phone", reason="Shared phone is still a distinct person", fingerprint=f"{index:064x}")
        for index in range(1, 700)])
    await db_session.flush()
    job = await enqueue_reconciliation(db_session, agency_id=group.agency_id, company_id=group.company_id,
        group_id=group.id, idempotency_key="durable-roster-700", now=datetime.now(UTC) + timedelta(seconds=1))
    for _ in range(7):
        result = await reconcile_page(db_session, job_id=job.id, crypto=crypto)
        assert result.processed == 100
    assert result.status == "succeeded" and result.total_processed == 700
    statuses = dict((await db_session.execute(select(TravellerMatchCaseModel.status,
        func.count()).group_by(TravellerMatchCaseModel.status))).all())
    assert statuses == {"provisional": 400, "unmatched": 300}
    kinds = dict((await db_session.execute(select(TravellerMatchCaseModel.source_kind,
        func.count()).group_by(TravellerMatchCaseModel.source_kind))).all())
    assert kinds == {"whatsapp_recipient": 1, "whatsapp_rejected": 699}
    first = await db_session.scalar(select(TravellerMatchCaseModel).where(TravellerMatchCaseModel.source_row_key == str(recipient.id)))
    assert first.traveller_id == people[0].id
    assert first.evidence["source_coverage"] == "durable_saved_rows_only"
    assert await db_session.scalar(select(func.count()).select_from(TravellerParticipationModel)) == 0
    assert (await reconcile_page(db_session, job_id=job.id, crypto=crypto)).processed == 0
    await require_fresh_match(db_session, case=first, group_revision=group.company_revision, crypto=crypto)
    recipient.name = "Changed roster person"
    await db_session.flush()
    with pytest.raises(ConflictError, match="source changed"):
        await require_fresh_match(db_session, case=first, group_revision=group.company_revision, crypto=crypto)
    refresh = await enqueue_reconciliation(db_session, agency_id=group.agency_id, company_id=group.company_id,
        group_id=group.id, idempotency_key="updated-roster", now=datetime.now(UTC) + timedelta(seconds=1))
    await reconcile_page(db_session, job_id=refresh.id, crypto=crypto)
    assert first.revision == 2
    await require_fresh_match(db_session, case=first, group_revision=group.company_revision, crypto=crypto)
