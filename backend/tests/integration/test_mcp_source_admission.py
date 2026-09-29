"""Oversized retained source values fail before canonical full-ORM export reads."""
from __future__ import annotations

import pytest
from sqlalchemy import event

from app.application.mcp.artifacts import ArtifactError
from app.application.mcp.exports import ExcelExportRequest
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from tests.integration.test_mcp_artifacts import artifacts as artifacts
from tests.integration.test_mcp_exports import person, service


@pytest.mark.parametrize("family", ["group_json", "passport_json", "passport_rows"])
async def test_oversized_scope_never_loads_large_source_models(artifacts, family):
    f = artifacts
    f.settings.mcp.export_source_byte_limit = 2048
    f.settings.mcp.export_source_row_limit = 2
    if family == "group_json":
        f.group.upload_configuration = {"oversized": "旅" * 4096}
        model = ClientGroupModel
    else:
        model = PassportSubmissionModel
        rows = [person(f, index) for index in range(3 if family == "passport_rows" else 1)]
        if family == "passport_json":
            rows[0].confirmed_fields = {"oversized": "旅" * 4096}
        f.session.add_all(rows)
    await f.session.commit()
    agency_id, group_id = f.agency.id, f.group.id
    f.session.expunge_all()

    def forbidden_load(*_args):
        raise AssertionError("Oversized source reached full ORM loading")

    event.listen(model, "load", forbidden_load)
    try:
        with pytest.raises(ArtifactError, match="configured .* limit"):
            await service(f).inspect(f.principal, ExcelExportRequest(agency_id=agency_id, group_ids=[group_id]))
    finally:
        event.remove(model, "load", forbidden_load)
