"""Unmatched requests cannot create permanent telemetry labels from user input."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import Response
from httpx import ASGITransport, AsyncClient

from app.infrastructure.observability.metrics import MetricsRegistry
from app.presentation.middleware import metrics as metrics_middleware


async def test_unmatched_paths_and_methods_have_bounded_metric_cardinality(monkeypatch):
    registry = MetricsRegistry()
    monkeypatch.setattr(metrics_middleware, "metrics", registry)
    app = FastAPI()
    app.add_middleware(metrics_middleware.MetricsMiddleware)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        for index in range(100):
            response = await client.request(f"CUSTOM{index}", f"/unknown/private-value-{index}")
            assert response.status_code == 404

    snapshot = registry.snapshot()
    assert snapshot["counters"] == {"http.requests.total.OTHER.404.unmatched": 100}
    assert list(snapshot["histograms"]) == ["http.requests.duration_ms.OTHER.unmatched"]
    assert "private-value" not in repr(snapshot)


async def test_known_routes_keep_their_template_in_metrics(monkeypatch):
    registry = MetricsRegistry()
    monkeypatch.setattr(metrics_middleware, "metrics", registry)
    app = FastAPI()
    app.add_middleware(metrics_middleware.MetricsMiddleware)

    @app.get("/documents/{document_id}")
    async def document(document_id: str):
        return {"id": document_id}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        assert (await client.get("/documents/private-document-one")).status_code == 200
        assert (await client.get("/documents/private-document-two")).status_code == 200

    snapshot = registry.snapshot()
    assert snapshot["counters"] == {"http.requests.total.GET.200.documents_{document_id}": 2}
    assert list(snapshot["histograms"]) == ["http.requests.duration_ms.GET.documents_{document_id}"]


async def test_rejections_before_routing_share_one_metric_series(monkeypatch):
    registry = MetricsRegistry()
    monkeypatch.setattr(metrics_middleware, "metrics", registry)
    app = FastAPI()

    @app.middleware("http")
    async def reject_request(_request, _call_next):
        return Response(status_code=429)

    app.add_middleware(metrics_middleware.MetricsMiddleware)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        for index in range(50):
            assert (await client.get(f"/unknown-{index}")).status_code == 429

    snapshot = registry.snapshot()
    assert snapshot["counters"] == {"http.requests.total.GET.429.unmatched": 50}
    assert len(snapshot["histograms"]) == 1
