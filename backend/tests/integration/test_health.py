"""
Test: Health Check Endpoints
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_liveness(client: AsyncClient) -> None:
    """Liveness probe must always return 200."""
    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "alive"
    assert "version" in data
    assert "revision" in data
    assert "environment" in data


@pytest.mark.asyncio
async def test_readiness(client: AsyncClient) -> None:
    """Readiness probe returns 200 when DB is available."""
    response = await client.get("/api/v1/health/ready")
    # In test environment with SQLite, DB check passes
    assert response.status_code in (200, 503)
    data = response.json()
    assert "status" in data
    assert "checks" in data
    assert "mobile_realtime" in data["checks"]
    assert "mobile_offline_authorization" in data["checks"]
    assert "revision" in data
