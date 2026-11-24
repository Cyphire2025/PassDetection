"""Docker qualification requests must honor canonical-company API contracts."""

from __future__ import annotations

import importlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from app.presentation.api.v1.schemas.client_group_schemas import CreateClientGroupRequest
from app.presentation.api.v1.schemas.company_schemas import CompanyCreateRequest


@pytest.fixture
def journey(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[4] / "scripts/qa"))
    return importlib.import_module("qualification_application_journey")


@pytest.mark.parametrize("prefix", ["Qualification Synthetic", "Synthetic Replica"])
async def test_qualification_group_uses_authenticated_company_and_live_request_contracts(
    journey, prefix,
):
    agency_id, company_id = uuid.uuid4(), uuid.uuid4()
    run_id = uuid.uuid4().hex
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        assert request.method == "POST"
        assert request.headers["Cookie"] == "access_token=synthetic-qualification-session"
        assert request.headers["Origin"] == "https://localhost:58443"
        if request.url.path == "/api/v1/companies":
            body = CompanyCreateRequest.model_validate_json(request.content)
            assert run_id in body.name
            assert request.url.params["agency_id"] == str(agency_id)
            return httpx.Response(201, json={"id": str(company_id), "status": "active"})
        assert requests == ["/api/v1/companies", "/api/v1/upload-links"]
        body = CreateClientGroupRequest.model_validate_json(request.content)
        assert body.company_id == company_id
        assert body.name == f"{prefix} {run_id}"
        assert body.travel_date >= datetime.now(UTC).date() + timedelta(days=29)
        assert body.return_date - body.travel_date == timedelta(days=3)
        configuration = body.upload_configuration
        assert configuration is not None
        assert configuration.passport_upload_pages == ["cover", "back_cover"]
        assert not configuration.passport_live_scan
        assert set(json.loads(request.content)["upload_configuration"]["required_fields"]) == set(
            journey.REQUIRED_FIELD_NAMES,
        )
        assert not any(configuration.required_fields.values())
        return httpx.Response(201, json={
            "id": str(uuid.uuid4()), "company_id": str(company_id),
            "agency_id": str(agency_id), "token": "synthetic-upload-link",
        })

    async with httpx.AsyncClient(
        base_url="https://qualification.test", transport=httpx.MockTransport(respond),
        headers={"Origin": "https://localhost:58443",
                 "Cookie": "access_token=synthetic-qualification-session"},
    ) as client:
        group = await journey.create_qualification_group(client, run_id, agency_id, prefix=prefix)
    assert group["company_id"] == str(company_id)
    assert requests == ["/api/v1/companies", "/api/v1/upload-links"]


@pytest.mark.parametrize("status", [403, 422])
async def test_qualification_stops_before_upload_link_if_company_creation_is_rejected(
    journey, status,
):
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(status, json={"detail": "Synthetic company request refused"})

    async with httpx.AsyncClient(
        base_url="https://qualification.test", transport=httpx.MockTransport(respond),
    ) as client:
        with pytest.raises(AssertionError, match=f"companies: expected 201, got {status}"):
            await journey.create_qualification_group(client, uuid.uuid4().hex, uuid.uuid4())
    assert requests == ["/api/v1/companies"]


@pytest.mark.parametrize("wrong_field", ["company_id", "agency_id"])
async def test_qualification_refuses_a_group_with_different_company_or_agency(
    journey, wrong_field,
):
    agency_id, company_id = uuid.uuid4(), uuid.uuid4()

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/companies":
            return httpx.Response(201, json={"id": str(company_id)})
        group = {"company_id": str(company_id), "agency_id": str(agency_id)}
        group[wrong_field] = str(uuid.uuid4())
        return httpx.Response(201, json=group)

    async with httpx.AsyncClient(
        base_url="https://qualification.test", transport=httpx.MockTransport(respond),
    ) as client:
        with pytest.raises(AssertionError, match="Qualification group .* mismatch"):
            await journey.create_qualification_group(client, uuid.uuid4().hex, agency_id)
