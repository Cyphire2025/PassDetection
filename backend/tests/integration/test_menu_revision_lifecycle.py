"""Saved meal snapshots, revision fences and foreign-organization IDs stay safe."""

from __future__ import annotations

import uuid

import pytest

from app.infrastructure.database.models import AgencyModel, UserModel
from tests.dashboard_session_fixtures import issue_dashboard_access


async def actor_headers(session):
    agency_id, user_id = uuid.uuid4(), uuid.uuid4()
    session.add(
        AgencyModel(
            id=agency_id, name="Synthetic menu lifecycle", email=f"{agency_id}@example.test"
        )
    )
    await session.flush()
    session.add(
        UserModel(
            id=user_id,
            agency_id=agency_id,
            email=f"{user_id}@example.test",
            full_name="Synthetic operator",
            hashed_password="unused",
            role="agency_admin",
            is_active=True,
        )
    )
    await session.commit()
    token, _ = await issue_dashboard_access(
        session, user_id=user_id, agency_id=agency_id, role="agency_admin"
    )
    return {"Authorization": f"Bearer {token}"}


async def library(client, headers):
    category = (
        await client.post(
            "/api/v1/menu/categories", json={"name": "Synthetic category"}, headers=headers
        )
    ).json()
    dishes = []
    for name in ("Dish A", "Dish B", "Dish C"):
        response = await client.post(
            f"/api/v1/menu/categories/{category['id']}/dishes",
            headers=headers,
            json={"name": name, "expected_category_updated_at": category["updated_at"]},
        )
        assert response.status_code == 201, response.text
        dishes.append(response.json())
        category = (await client.get("/api/v1/menu", headers=headers)).json()["categories"][0]
    response = await client.post(
        "/api/v1/menu/plans/generate",
        headers=headers,
        json={
            "name": "Synthetic saved plan",
            "trip_days": 1,
            "category_ids": [category["id"]],
            "expected_category_revisions": {category["id"]: category["updated_at"]},
        },
    )
    assert response.status_code == 201, response.text
    return category, dishes, response.json()


@pytest.mark.asyncio
async def test_regeneration_and_deletions_preserve_saved_snapshots_and_revision_fences(
    client, db_session
):
    headers = await actor_headers(db_session)
    category, dishes, plan = await library(client, headers)
    duplicate = await client.post(
        f"/api/v1/menu/categories/{category['id']}/dishes",
        headers=headers,
        json={"name": dishes[0]["name"], "expected_category_updated_at": category["updated_at"]},
    )
    assert duplicate.status_code == 409
    regenerate = await client.post(
        f"/api/v1/menu/plans/{plan['id']}/regenerate",
        headers=headers,
        json={
            "expected_updated_at": plan["updated_at"],
            "expected_category_revisions": {category["id"]: category["updated_at"]},
        },
    )
    assert regenerate.status_code == 200, regenerate.text
    current = regenerate.json()
    stale = await client.request(
        "DELETE",
        f"/api/v1/menu/plans/{plan['id']}",
        headers=headers,
        json={"expected_updated_at": plan["updated_at"]},
    )
    assert stale.status_code == 409
    used = current["days"][0]["lunch"][0]
    dish = next(item for item in dishes if item["id"] == used["dish_id"])
    deleted_dish = await client.request(
        "DELETE",
        f"/api/v1/menu/dishes/{dish['id']}",
        headers=headers,
        json={
            "expected_updated_at": dish["updated_at"],
            "expected_category_updated_at": category["updated_at"],
        },
    )
    assert deleted_dish.status_code == 204, deleted_dish.text
    workspace = (await client.get("/api/v1/menu", headers=headers)).json()
    assert workspace["plans"][0]["days"][0]["lunch"][0]["dish_name"] == used["dish_name"]
    category = workspace["categories"][0]
    deleted_category = await client.request(
        "DELETE",
        f"/api/v1/menu/categories/{category['id']}",
        headers=headers,
        json={"expected_updated_at": category["updated_at"]},
    )
    assert deleted_category.status_code == 204, deleted_category.text
    workbook = await client.get(f"/api/v1/menu/plans/{plan['id']}/export.xlsx", headers=headers)
    assert workbook.status_code == 200 and workbook.content.startswith(b"PK")
    workspace = (await client.get("/api/v1/menu", headers=headers)).json()
    assert workspace["categories"] == []
    assert workspace["plans"][0]["days"][0]["lunch"][0]["dish_name"] == used["dish_name"]
    deleted_plan = await client.request(
        "DELETE",
        f"/api/v1/menu/plans/{plan['id']}",
        headers=headers,
        json={"expected_updated_at": current["updated_at"]},
    )
    assert deleted_plan.status_code == 204, deleted_plan.text
    assert (await client.get("/api/v1/menu", headers=headers)).json()["plans"] == []


@pytest.mark.asyncio
async def test_foreign_category_dish_plan_and_download_ids_are_hidden(client, db_session):
    owner = await actor_headers(db_session)
    category, dishes, plan = await library(client, owner)
    other = await actor_headers(db_session)
    requests = [
        (
            "PATCH",
            f"/api/v1/menu/categories/{category['id']}",
            {"name": "Foreign rename", "expected_updated_at": category["updated_at"]},
        ),
        (
            "PATCH",
            f"/api/v1/menu/dishes/{dishes[0]['id']}",
            {
                "name": "Foreign dish",
                "expected_updated_at": dishes[0]["updated_at"],
                "expected_category_updated_at": category["updated_at"],
            },
        ),
        (
            "PATCH",
            f"/api/v1/menu/plans/{plan['id']}",
            {"name": "Foreign plan", "expected_updated_at": plan["updated_at"]},
        ),
    ]
    for method, path, body in requests:
        response = await client.request(method, path, headers=other, json=body)
        assert response.status_code == 404, response.text
    download = await client.get(f"/api/v1/menu/plans/{plan['id']}/export.xlsx", headers=other)
    assert download.status_code == 404
    assert (await client.get("/api/v1/menu", headers=other)).json()["plans"] == []
    original = (await client.get("/api/v1/menu", headers=owner)).json()
    assert original["categories"][0]["name"] == category["name"]
    assert original["plans"][0]["name"] == plan["name"]
