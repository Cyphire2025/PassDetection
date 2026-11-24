"""Activity compatibility exports and real HTTP validation remain usable."""

from __future__ import annotations

import importlib
import inspect
import pickle
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.presentation.api.v1.routes import whatsapp_activity as activity

_OWNER_HELPERS = {
    "access": ("_ensure_kind_access", "_scope_client_group_statement"),
    "status": ("_normalized_activity_status", "_status_aggregates", "_failed_status_predicate"),
    "summary_queries": (
        "_broadcast_activity_statement", "_document_activity_statement", "_qr_activity_statement",
    ),
    "document_queries": (
        "_document_activity_deliveries_statement", "_document_activity_status_predicate",
    ),
    "failure_queries": (
        "_broadcast_failures_statement", "_document_failures_statement", "_qr_failures_statement",
    ),
}


def test_legacy_exports_are_real_owner_functions_with_resolvable_annotations() -> None:
    for suffix, names in _OWNER_HELPERS.items():
        owner = importlib.import_module(f"{activity.__name__}_{suffix}")
        for name in names:
            function = getattr(activity, name)
            assert function is getattr(owner, name)
            assert function.__module__ == activity.__name__
            assert function.__qualname__ == name
            assert pickle.loads(pickle.dumps(function)) is function
            assert Path(inspect.getsourcefile(function)).stem == f"whatsapp_activity_{suffix}"
            assert "return" in get_type_hints(function)
            for global_name, value in inspect.getclosurevars(function).globals.items():
                if hasattr(activity, global_name):
                    assert value is getattr(activity, global_name)
    for name in ("_activity_statement", "_failures_statement", "_activity_title",
                 "get_whatsapp_activity_summary", "get_document_activity_deliveries",
                 "get_whatsapp_activity_failures"):
        assert "return" in get_type_hints(getattr(activity, name))


@pytest.mark.parametrize("query", [
    {"limit": "0"}, {"limit": "101"}, {"offset": "-1"},
    {"q": "x" * 121}, {"status_filter": "unsupported"},
])
async def test_document_activity_http_rejects_unbounded_or_unknown_filters(query: dict[str, str]) -> None:
    app = FastAPI()
    app.include_router(activity.router, prefix="/whatsapp")
    route = next(route for route in activity.router.routes if route.name == "get_document_activity_deliveries")
    session = SimpleNamespace(execute=AsyncMock())
    app.dependency_overrides[route.dependant.dependencies[0].call] = lambda: object()
    app.dependency_overrides[activity.get_db_session] = lambda: session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/whatsapp/activities/document/{uuid.uuid4()}/deliveries", params=query)
    assert response.status_code == 422
    session.execute.assert_not_awaited()
