"""Actual SDK HTTP diagnostics use only the explicit sealed-mount setting."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.core.config.mcp import MCPSettings
from tests.integration.test_mcp_authorization import call_mcp, connect, mcp_fixture  # noqa: F401
from tests.unit.infrastructure.test_mcp_log_runs import sealed


def test_diagnostic_setting_defaults_off_and_rejects_relative_paths():
    assert MCPSettings(_env_file=None).diagnostic_log_root is None
    with pytest.raises(ValidationError):
        MCPSettings(_env_file=None, diagnostic_log_root="relative/raw/logs")


async def test_sdk_mount_reads_fresh_sealed_projection_and_tamper_becomes_unavailable(mcp_fixture, tmp_path):  # noqa: F811
    client, _, settings, _, _, _ = mcp_fixture
    settings.mcp.diagnostic_log_root = tmp_path
    run, manifest = sealed(tmp_path)
    _, tokens = await connect(mcp_fixture, scopes=["mcp:diagnose"])
    response = await call_mcp(client, tokens["access_token"], name="inspect_diagnostics", arguments={"sources": ["api"]})
    result = response.json()["result"]["structuredContent"]
    assert result["sources"]["api"]["match_status"] == "matched"
    assert result["sources"]["api"]["collector_observed_at"] == manifest["finished_at"]
    assert result["sources"]["api"]["coverage"] == "retained_tail_only"
    assert result["absence_of_matches_does_not_establish_health"] is True
    manifest["sources"]["api"]["sha256"] = "a" * 64
    (run / "manifest.json").write_text(json.dumps(manifest))
    response = await call_mcp(client, tokens["access_token"], name="inspect_diagnostics", arguments={"sources": ["api"]})
    source = response.json()["result"]["structuredContent"]["sources"]["api"]
    assert source["status"] == "unavailable" and source["reason"] == "collector_integrity_failed"
