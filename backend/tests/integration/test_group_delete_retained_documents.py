"""Source deletion respects independently retained originals and pending copies."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.domain.exceptions.exceptions import ValidationError
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentAssetModel as Asset,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentRevisionModel as Document,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerParticipationModel as Participation,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerProfileModel as Person,
)
from app.presentation.api.v1.routes import client_groups
from tests.integration.test_company_people import people_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("copy_pending", [False, True])
async def test_permanent_group_delete_preserves_retained_documents(
    db_session,
    monkeypatch,
    copy_pending: bool,
):
    context, person, user = await people_fixture(db_session)
    document = await db_session.scalar(select(Document))
    participation = await db_session.scalar(select(Participation))
    assets = list((await db_session.scalars(select(Asset))).all())
    retained_keys = [asset.object_key for asset in assets]
    provenance = dict(document.source_provenance)
    source_id, group_id, person_id = context.source.id, context.group.id, person.id
    document_id, participation_id = document.id, participation.id
    context.group.status = "archived"
    if copy_pending:
        assets[0].availability = "pending"
        assets[0].source_object_key = context.source.image_s3_key
    await db_session.commit()
    # These collaborators concern independent WhatsApp delivery synchronization.
    # Exercise real group authorization, retention, row deletion and commit here.
    for name in (
        "lock_linked_whatsapp_broadcast_groups",
        "prepare_private_delivery_identity_mutation",
        "sync_group_broadcast_contacts",
    ):
        monkeypatch.setattr(client_groups, name, AsyncMock())

    if copy_pending:
        with pytest.raises(ValidationError, match="copies are still processing"):
            await client_groups.permanently_delete_client_group(
                group_id,
                retain_records=False,
                current_user=user,
                session=db_session,
            )
        await db_session.rollback()
    else:
        result = await client_groups.permanently_delete_client_group(
            group_id,
            retain_records=False,
            current_user=user,
            session=db_session,
        )
        assert result["deleted"] is True
        assert result["deleted_passport_submissions"] == 1

    db_session.expire_all()
    source = await db_session.get(PassportSubmissionModel, source_id)
    group = await db_session.get(ClientGroupModel, group_id)
    document = await db_session.get(Document, document_id)
    participation = await db_session.get(Participation, participation_id)
    assert (source is not None) is copy_pending
    assert group.status == ("archived" if copy_pending else "deleted")
    assert await db_session.get(Person, person_id) is not None
    assert document.source_provenance == provenance
    assert document.source_submission_id == (source_id if copy_pending else None)
    assert document.source_group_id == (group_id if copy_pending else None)
    assert participation.source_submission_id == (source_id if copy_pending else None)
    retained_assets = list((await db_session.scalars(select(Asset))).all())
    assert [asset.object_key for asset in retained_assets] == retained_keys
    assert all(asset.object_key.startswith("travellers/") for asset in retained_assets)
