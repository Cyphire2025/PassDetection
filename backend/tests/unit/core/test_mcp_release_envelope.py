"""A restricted deployment cannot discover or resume disabled export families."""

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.core.config.mcp import MCPSettings
from app.presentation.mcp.server import install_mcp


@pytest.mark.asyncio
async def test_passport_only_deployment_omits_other_export_tools_and_operations(test_settings):
    settings = test_settings.model_copy(update={"mcp": MCPSettings(
        _env_file=None, export_families=["passport_excel"],
        export_source_row_limit=100, export_source_byte_limit=1024 * 1024,
    )})
    app = FastAPI()
    install_mcp(app, settings)
    names = {tool.name for tool in await app.state.mcp_server.list_tools()}
    assert {"inspect_excel_export_options", "inspect_excel_export", "prepare_excel_export", "resume_excel_export"} <= names
    for suffix in ("image_export", "tracking_export", "rooming_export", "document_assignment_export"):
        assert not {f"{action}_{suffix}" for action in ("inspect", "prepare", "resume")} & names
        assert f"prepare_{suffix}" not in app.state.mcp_operations
    assert "prepare_excel_export" in app.state.mcp_operations


@pytest.mark.asyncio
async def test_no_export_families_registers_no_export_preparation(test_settings):
    settings = test_settings.model_copy(update={"mcp": MCPSettings(_env_file=None, export_families=[])})
    app = FastAPI()
    install_mcp(app, settings)
    assert not any(name.endswith("_export") for name in app.state.mcp_operations)
    assert "inspect_excel_export_options" not in {
        tool.name for tool in await app.state.mcp_server.list_tools()
    }
    assert {"list_group_export_history", "get_group_export_history"} <= {
        tool.name for tool in await app.state.mcp_server.list_tools()
    }


@pytest.mark.parametrize("overrides", [
    {"export_families": ["arbitrary_files"]},
    {"export_source_row_limit": 0}, {"export_source_row_limit": 1501},
    {"export_source_byte_limit": 0}, {"export_source_byte_limit": 16 * 1024 * 1024 + 1},
])
def test_release_envelope_rejects_unreviewed_or_unbounded_settings(overrides):
    with pytest.raises(ValidationError):
        MCPSettings(_env_file=None, **overrides)
