"""Unexpected export failures retain retry/audit identity without secret diagnostics."""

import json
import logging
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import structlog
from fastapi import FastAPI
from sqlalchemy import select

from app.core.logging.logger import _StdlibStructuredLogger
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import AuditLogModel
from app.presentation.mcp import export_tools
from tests.integration.test_mcp_artifacts import artifacts as artifacts


@pytest.mark.parametrize("stdlib_fallback", [False, True])
@pytest.mark.parametrize("chain", ["explicit", "implicit", "suppressed", "none"])
async def test_unexpected_error_logs_only_types_and_ids_and_retains_retry(
    artifacts, monkeypatch, caplog, stdlib_fallback, chain
):
    f = artifacts
    operation_id, workflow_id = uuid.uuid4(), uuid.uuid4()
    secret = "PRIVATE_EXPORT_SENTINEL_signed_url_token_source_payload"
    initial = {"data": {"retained_input": secret}}
    operation = MCPOperationModel(
        id=operation_id,
        user_id=f.principal.user_id,
        initial_grant_id=f.principal.grant_id,
        operation_name="prepare_excel_export",
        capability="mcp:export",
        idempotency_hash="a" * 64,
        payload_hash="b" * 64,
        initial_result=initial,
        workflow_id=workflow_id,
        status="queued",
        progress=0,
        stage="queued",
        revision=0,
        created_entities=[],
    )
    f.session.add(operation)
    await f.session.commit()

    @asynccontextmanager
    async def sessions():
        yield f.session

    app = FastAPI()
    app.state.mcp_session_factory = sessions
    app.state.mcp_artifact_storage = f.storage
    monkeypatch.setattr(
        export_tools,
        "get_access_token",
        lambda: SimpleNamespace(
            token=secret,
            subject=str(f.principal.user_id),
            claims={"grant_id": str(f.principal.grant_id)},
        ),
    )
    name = "mcp.export.failure.test"
    if stdlib_fallback:
        safe_logger = _StdlibStructuredLogger(name)
    else:
        safe_logger = structlog.wrap_logger(
            logging.getLogger(name),
            processors=[structlog.processors.JSONRenderer()],
            wrapper_class=structlog.stdlib.BoundLogger,
        )
    monkeypatch.setattr(export_tools, "logger", safe_logger)

    async def fail(self, *, access_token, operation_id):
        assert access_token == secret
        retained = await self.session.get(MCPOperationModel, operation_id)
        retained.status = "running"
        await self.session.flush()
        if chain == "none":
            raise RuntimeError(secret)
        try:
            raise ValueError(secret + "_cause")
        except ValueError as cause:
            if chain == "explicit":
                raise RuntimeError(secret) from cause
            if chain == "suppressed":
                raise RuntimeError(secret) from None
            raise RuntimeError(secret)

    monkeypatch.setattr(export_tools.MCPExcelExportService, "generate", fail)
    caplog.set_level(logging.ERROR)
    result = await export_tools._invoke_export(
        app, f.settings, name="resume_excel_export", operation_id=operation_id
    )
    assert result["error"] == "export_failed"
    assert result["operation_id"] == str(operation_id)
    assert result["completeness"] == "unavailable"
    assert "operation ID" in result["message"]
    audit = await f.session.get(AuditLogModel, uuid.UUID(result["audit_id"]))
    assert audit.action == "mcp.tool.resume_excel_export"
    assert audit.entity_id == str(operation_id) and audit.result == "failed"
    assert audit.user_id == f.principal.user_id
    retained = await f.session.scalar(
        select(MCPOperationModel).where(MCPOperationModel.id == operation_id)
    )
    assert retained.status == "queued" and retained.revision == 0
    assert retained.initial_result == initial and retained.workflow_id == workflow_id
    assert not f.storage.objects
    records = [record for record in caplog.records if record.name == name]
    assert len(records) == 1
    record = records[0]
    assert record.exc_info is None and record.stack_info is None
    assert secret not in caplog.text and secret not in json.dumps(result)
    assert "Traceback" not in caplog.text
    expected = {
        "operation_id": str(operation_id),
        "tool_name": "resume_excel_export",
        "error_type": "RuntimeError",
        "cause_type": "ValueError" if chain in {"explicit", "implicit"} else None,
    }
    if stdlib_fallback:
        assert record.args == ("mcp_excel_export_failed", expected)
    else:
        assert json.loads(record.getMessage()) == {"event": "mcp_excel_export_failed", **expected}
