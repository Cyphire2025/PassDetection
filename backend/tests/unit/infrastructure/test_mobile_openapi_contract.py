from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.export_mobile_openapi_contract import canonical_json, mobile_contract

_MOBILE_CONTRACT = (
    Path(__file__).resolve().parents[3] / ".." / "mobile" / "contracts" / "mobile-api.openapi.json"
).resolve()


def test_mobile_contract_keeps_only_mobile_paths_and_reachable_schemas() -> None:
    source = {
        "openapi": "3.1.0",
        "info": {"title": "Example", "version": "1"},
        "paths": {
            "/api/v1/mobile/trips": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/TripPage"}
                                }
                            }
                        }
                    }
                }
            },
            "/api/v1/dashboard": {"get": {"responses": {"200": {}}}},
        },
        "components": {
            "schemas": {
                "TripPage": {
                    "properties": {"items": {"items": {"$ref": "#/components/schemas/Trip"}}}
                },
                "Trip": {"type": "object"},
                "DashboardOnly": {"type": "object"},
            },
            "securitySchemes": {"Bearer": {"type": "http", "scheme": "bearer"}},
        },
    }

    contract = mobile_contract(source)

    assert list(contract["paths"]) == ["/api/v1/mobile/trips"]
    assert set(contract["components"]["schemas"]) == {"Trip", "TripPage"}
    assert "DashboardOnly" not in canonical_json(contract)
    assert json.loads(canonical_json(contract)) == contract


def test_mobile_contract_fails_closed_on_a_missing_referenced_schema() -> None:
    with pytest.raises(ValueError, match="Missing"):
        mobile_contract(
            {
                "paths": {
                    "/api/v1/mobile/trips": {
                        "get": {
                            "responses": {
                                "200": {"schema": {"$ref": "#/components/schemas/Missing"}}
                            }
                        }
                    }
                },
                "components": {"schemas": {}},
            }
        )


def test_checked_in_my_photos_download_operation_id_matches_the_runtime_handler() -> None:
    contract = json.loads(_MOBILE_CONTRACT.read_text(encoding="utf-8"))
    operation = contract["paths"][
        "/api/v1/mobile/trips/{group_id}/my-photos/download-authorizations/"
        "{authorization_id}/content"
    ]["get"]

    assert operation["operationId"] == (
        "get_my_photos_download_api_v1_mobile_trips__group_id__my_photos_"
        "download_authorizations__authorization_id__content_get"
    )
    assert "development" not in operation["operationId"]
