from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.presentation.api.v1.schemas.client_group_schemas import (
    CreateClientGroupRequest,
    ReplaceWhatsAppBroadcastLinksRequest,
    UpdateClientGroupRequest,
)
from app.presentation.middleware.error_handler import register_exception_handlers


def application() -> tuple[FastAPI, list[str]]:
    app = FastAPI()
    register_exception_handlers(app)
    saved: list[str] = []

    @app.post("/create", status_code=201)
    async def create(body: CreateClientGroupRequest) -> dict[str, object]:
        saved.append(body.name)
        return {"cities": body.departure_cities, "questions": body.custom_questions}

    @app.post("/update", status_code=201)
    async def update(body: UpdateClientGroupRequest) -> dict[str, object]:
        saved.append(body.name)
        return {"cities": body.departure_cities, "questions": body.custom_questions}

    @app.post("/links", status_code=201)
    async def links(body: ReplaceWhatsAppBroadcastLinksRequest) -> dict[str, object]:
        saved.append("links")
        return {"broadcast_ids": body.whatsapp_broadcast_group_ids}

    return app, saved


def payload() -> dict[str, object]:
    return {
        "company_id": str(uuid.UUID("11111111-1111-4111-8111-111111111111")),
        "name": "Synthetic group",
        "destination": "Synthetic destination",
        "travel_date": "2026-12-07",
        "return_date": "2026-12-10",
        "nearest_international_airport_enabled": True,
        "departure_cities": ["Delhi"],
    }


def question(options: object) -> dict[str, object]:
    return {
        "id": "22222222-2222-4222-8222-222222222222",
        "label": "Synthetic preference",
        "options": options,
    }


@pytest.mark.parametrize("path", ["/create", "/update"])
@pytest.mark.parametrize("field", ["departure_cities", "options"])
@pytest.mark.parametrize(
    "value",
    [
        "SYNTHETIC_PRIVATE_INPUT",
        {"SYNTHETIC_PRIVATE_KEY": "A", "B": "C"},
        [None, "A"],
        [1, 2],
        ["A", "B"] * 26,
    ],
    ids=["string", "object", "null-member", "number-member", "raw-over-limit"],
)
async def test_collection_lists_reject_malformed_or_over_limit_json_before_side_effects(
    path: str,
    field: str,
    value: object,
) -> None:
    app, saved = application()
    body = payload()
    body[field if field == "departure_cities" else "custom_questions"] = (
        value if field == "departure_cities" else [question(value)]
    )
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post(path, json=body)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"
    assert "SYNTHETIC_PRIVATE" not in response.text
    assert saved == []


@pytest.mark.parametrize("path", ["/create", "/update"])
async def test_valid_choices_keep_first_spelling_and_existing_normalization(path: str) -> None:
    app, saved = application()
    body = {
        **payload(),
        "departure_cities": [" Delhi ", "delhi", "", "Mumbai"],
        "custom_questions": [question([" Vegetarian ", "vegetarian", "", "Vegan"])],
    }
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post(path, json=body)
    assert response.status_code == 201, response.text
    assert response.json()["cities"] == ["Delhi", "Mumbai"]
    assert response.json()["questions"][0]["options"] == ["Vegetarian", "Vegan"]
    assert saved == ["Synthetic group"]


@pytest.mark.parametrize("path", ["/create", "/update"])
async def test_disabled_airport_choice_still_accepts_null_as_empty(path: str) -> None:
    app, saved = application()
    body = {**payload(), "nearest_international_airport_enabled": False, "departure_cities": None}
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post(path, json=body)
    assert response.status_code == 201, response.text
    assert response.json()["cities"] == []
    assert saved == ["Synthetic group"]


async def test_import_creation_keeps_discarding_disabled_collection_fields() -> None:
    app, saved = application()
    body = {
        **payload(),
        "import_only": True,
        "departure_cities": "ignored",
        "custom_questions": [question("ignored")],
    }
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/create", json=body)
    assert response.status_code == 201, response.text
    assert response.json() == {"cities": [], "questions": []}
    assert saved == ["Synthetic group"]


@pytest.mark.parametrize("path", ["/create", "/update", "/links"])
@pytest.mark.parametrize(
    "value",
    [
        "SYNTHETIC_PRIVATE_INPUT",
        {"SYNTHETIC_PRIVATE_KEY": "value"},
        [{"SYNTHETIC_PRIVATE_KEY": "value"}],
        [["SYNTHETIC_PRIVATE_INPUT"]],
        [None],
        ["33333333-3333-4333-8333-333333333333"] * 51,
    ],
    ids=["string", "object", "object-member", "list-member", "null-member", "raw-over-limit"],
)
async def test_broadcast_lists_reject_invalid_json_without_server_errors_or_side_effects(
    path: str, value: object,
) -> None:
    app, saved = application()
    body = {} if path == "/links" else payload()
    body["whatsapp_broadcast_group_ids"] = value
    transport = ASGITransport(app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(path, json=body)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"
    assert "SYNTHETIC_PRIVATE" not in response.text
    assert saved == []


@pytest.mark.parametrize("path", ["/create", "/update", "/links"])
async def test_valid_broadcast_ids_keep_first_order_and_deduplicate(path: str) -> None:
    app, saved = application()
    first = "33333333-3333-4333-8333-333333333333"
    second = "44444444-4444-4444-8444-444444444444"
    body = {} if path == "/links" else payload()
    body["whatsapp_broadcast_group_ids"] = [first, second, first]
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post(path, json=body)
    assert response.status_code == 201, response.text
    if path == "/links":
        assert response.json()["broadcast_ids"] == [first, second]
    assert len(saved) == 1


@pytest.mark.parametrize(
    "matching",
    [
        [],
        {str(uuid.UUID(int=index + 1)): ["name"] for index in range(51)},
        {"SYNTHETIC_PRIVATE_KEY": ["name"]},
        {"33333333-3333-4333-8333-333333333333": "SYNTHETIC_PRIVATE_INPUT"},
        {"33333333-3333-4333-8333-333333333333": [None]},
        {"33333333-3333-4333-8333-333333333333": ["a" * 65]},
        {"33333333-3333-4333-8333-333333333333": [" - "]},
        {"33333333-3333-4333-8333-333333333333": [f"field_{index}" for index in range(33)]},
        {"44444444-4444-4444-8444-444444444444": ["name"]},
    ],
    ids=["shape", "broadcast-count", "uuid", "field-list", "field-type", "field-length", "empty", "field-count", "unselected"],
)
async def test_matching_field_contract_rejects_invalid_or_unselected_broadcasts(
    matching: object,
) -> None:
    app, saved = application()
    body = {
        "whatsapp_broadcast_group_ids": ["33333333-3333-4333-8333-333333333333"],
        "matching_fields_by_broadcast": matching,
    }
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/links", json=body)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"
    assert "SYNTHETIC_PRIVATE" not in response.text
    assert saved == []
