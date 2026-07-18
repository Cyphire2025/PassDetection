from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    QualifierSelectionModel,
)


@pytest.mark.asyncio
async def test_public_qualifier_create_and_resume_api(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    agency_id = uuid.uuid4()
    token = "public-qualifier-enabled-token-123456"
    db_session.add(
        AgencyModel(
            id=agency_id,
            name="Qualifier Agency",
            email=f"{agency_id}@example.com",
        )
    )
    db_session.add(
        ClientGroupModel(
            id=uuid.uuid4(),
            name="Qualifier Group",
            token=token,
            agency_id=agency_id,
            status="active",
            created_by_user_id=None,
            relation_with_qualifier_enabled=True,
        )
    )
    await db_session.commit()
    upload_headers = {
        "X-Upload-Session-ID": "bootstrap-qualifier-flow-12345678"
    }

    group_response = await client.get(
        f"/api/v1/upload-links/token/{token}",
        headers=upload_headers,
    )
    assert group_response.status_code == 200
    group_payload = group_response.json()
    assert group_payload["relation_with_qualifier_enabled"] is True
    assert "friend" not in {
        option["code"]
        for option in group_payload["qualifier_relation_options"]
    }

    create_response = await client.post(
        f"/api/v1/upload-links/token/{token}/qualifier-selection",
        json={"is_self": False, "relation_code": "spouse"},
        headers=upload_headers,
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["relation_code"] == "spouse"
    assert created["relation_label"] == "Spouse"
    assert created["status"] == "active"
    selection_token = created["selection_token"]

    persisted = (
        await db_session.execute(select(QualifierSelectionModel))
    ).scalar_one()
    assert persisted.token_hash != selection_token

    resume_response = await client.get(
        f"/api/v1/upload-links/token/{token}/qualifier-selection",
        headers={
            **upload_headers,
            "X-Qualifier-Selection-Token": selection_token,
        },
    )
    assert resume_response.status_code == 200
    resumed = resume_response.json()
    assert resumed["relation_code"] == "spouse"
    assert resumed["status"] == "active"
    assert "selection_token" not in resumed


@pytest.mark.asyncio
async def test_public_qualifier_api_rejects_disabled_and_disallowed_values(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    agency_id = uuid.uuid4()
    token = "public-qualifier-disabled-token-12345"
    db_session.add(
        AgencyModel(
            id=agency_id,
            name="Legacy Agency",
            email=f"{agency_id}@example.com",
        )
    )
    db_session.add(
        ClientGroupModel(
            id=uuid.uuid4(),
            name="Legacy Group",
            token=token,
            agency_id=agency_id,
            status="active",
            created_by_user_id=None,
            relation_with_qualifier_enabled=False,
        )
    )
    await db_session.commit()
    upload_headers = {
        "X-Upload-Session-ID": "bootstrap-disabled-flow-12345678"
    }

    disabled = await client.post(
        f"/api/v1/upload-links/token/{token}/qualifier-selection",
        json={"is_self": True},
        headers=upload_headers,
    )
    assert disabled.status_code == 400

    group = (
        await db_session.execute(
            select(ClientGroupModel).where(ClientGroupModel.token == token)
        )
    ).scalar_one()
    group.relation_with_qualifier_enabled = True
    await db_session.commit()

    friend = await client.post(
        f"/api/v1/upload-links/token/{token}/qualifier-selection",
        json={"is_self": False, "relation_code": "friend"},
        headers=upload_headers,
    )
    assert friend.status_code == 400

    both = await client.post(
        f"/api/v1/upload-links/token/{token}/qualifier-selection",
        json={"is_self": True, "relation_code": "spouse"},
        headers=upload_headers,
    )
    assert both.status_code == 422
