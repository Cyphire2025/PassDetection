"""Exercise real tenant-scoped office counts, coordinator identities and groups."""

from __future__ import annotations

import uuid
from datetime import date

from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
    PassportSubmissionModel,
    UserModel,
)
from tests.dashboard_session_fixtures import issue_dashboard_access
from tests.persistence import persist_graph


async def test_office_coordinator_and_group_projections_cannot_mix_tenants(client, db_session):
    owner_id, agency_id, own_coordinator, own_group = (uuid.uuid4() for _ in range(4))
    records = [
        AgencyModel(id=agency_id, name="Synthetic office", email="office@example.com"),
        UserModel(
            id=owner_id,
            agency_id=agency_id,
            email="office-owner@example.com",
            full_name="Office owner",
            hashed_password="unused",
            role="agency_admin",
        ),
    ]
    other_agency, other_coordinator, other_group = (uuid.uuid4() for _ in range(3))
    records.append(
        AgencyModel(id=other_agency, name="Foreign office", email="foreign-office@example.com")
    )
    for tenant, coordinator, group_id, count in (
        (agency_id, own_coordinator, own_group, 1),
        (other_agency, other_coordinator, other_group, 3),
    ):
        records.extend(
            [
                UserModel(
                    id=coordinator,
                    agency_id=tenant,
                    email=f"{coordinator}@example.com",
                    full_name=f"Synthetic coordinator {count}",
                    hashed_password="unused",
                    role="agency_coordinator",
                    is_active=True,
                ),
                ClientGroupModel(
                    id=group_id,
                    agency_id=tenant,
                    token=str(uuid.uuid4()),
                    name=f"Synthetic trip {count}",
                    travel_date=date(2027, 2, 1),
                    return_date=date(2027, 2, 10),
                    status="active",
                ),
                CoordinatorGroupAssignmentModel(
                    agency_id=tenant,
                    group_id=group_id,
                    coordinator_user_id=coordinator,
                    active=True,
                ),
            ]
        )
        records.extend(
            PassportSubmissionModel(
                agency_id=tenant,
                group_id=group_id,
                client_name=f"Synthetic passenger {index}",
                image_s3_key=f"synthetic/{group_id}/{index}.jpg",
                status="confirmed",
            )
            for index in range(count)
        )
    await persist_graph(db_session, records)
    await db_session.commit()
    access, _ = await issue_dashboard_access(
        db_session, user_id=owner_id, agency_id=agency_id, role="agency_admin"
    )
    headers = {"Authorization": f"Bearer {access}"}
    coordinators = await client.get("/api/v1/tour-operations/coordinators", headers=headers)
    assert coordinators.status_code == 200, coordinators.text
    rows = coordinators.json()
    assert [row["id"] for row in rows] == [str(own_coordinator)]
    assert rows[0]["assigned_groups_count"] == rows[0]["assigned_passengers_count"] == 1
    groups = await client.get("/api/v1/tour-operations/groups", headers=headers)
    assert groups.status_code == 200, groups.text
    rows = groups.json()
    assert [row["id"] for row in rows] == [str(own_group)]
    assert rows[0]["passenger_count"] == rows[0]["assigned_passengers_count"] == 1
    assert rows[0]["unassigned_passengers_count"] == 0
    assert [row["coordinator_id"] for row in rows[0]["coordinators"]] == [str(own_coordinator)]
    assert str(other_coordinator) not in groups.text + coordinators.text
