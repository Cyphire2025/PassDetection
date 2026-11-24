"""Configured JSON, console and stdlib fallback redact automatic task records."""

from __future__ import annotations

import logging
import uuid

import pytest

from app.core.logging import logger as application_logging
from app.core.logging.celery_diagnostics import CeleryTaskDiagnosticFilter
from app.core.logging.task_diagnostics import task_failure_diagnostic
from app.infrastructure.whatsapp.cloud_api_provider import WhatsAppCloudApiError
from tests.unit.core.test_logging_configuration import isolated_logging as isolated_logging


@pytest.mark.parametrize("mode", ["json", "console", "stdlib"])
def test_configured_task_failure_keeps_safe_code_without_private_values(
    isolated_logging, monkeypatch, mode
):
    _, output, settings = isolated_logging
    settings.is_production = mode != "console"
    if mode == "stdlib":
        monkeypatch.setattr(application_logging, "structlog", None)
    application_logging.configure_logging()
    private = "synthetic-private-passport-and-token"
    context = {
        "id": str(uuid.uuid4()),
        "name": "synthetic.private.failure",
        "exc": private,
        "kwargs": {"passport_link": private},
    }
    try:
        raise WhatsAppCloudApiError(private, code="WHATSAPP_PROVIDER_RATE_LIMITED", transient=True)
    except WhatsAppCloudApiError:
        logging.getLogger("celery.app.trace").error(
            "Task %(name)s[%(id)s] failed: %(exc)s",
            context,
            exc_info=True,
            extra={"data": context},
        )

    rendered = output.getvalue()
    assert private not in rendered
    assert "WHATSAPP_PROVIDER_RATE_LIMITED" in rendered
    assert "task_failed" in rendered


def test_task_log_projection_is_idempotent_and_does_not_mutate_payload():
    private = "synthetic-private-payload"
    context = {"name": "synthetic.task", "id": str(uuid.uuid4()), "kwargs": {"value": private}}
    record = logging.LogRecord(
        "celery.worker.strategy", logging.INFO, __file__, 1, "Task received", (context,), None
    )
    record.data = context
    projection = CeleryTaskDiagnosticFilter()
    assert projection.filter(record)
    once = dict(record.__dict__)
    assert projection.filter(record)
    assert record.__dict__ == once
    assert context["kwargs"] == {"value": private}
    assert private not in str(record.__dict__)


def test_success_log_keeps_runtime_without_reporting_a_failure():
    context = {
        "name": "synthetic.task",
        "id": str(uuid.uuid4()),
        "return_value": "synthetic-private-result",
        "runtime": 1.25,
    }
    record = logging.LogRecord(
        "celery.app.trace", logging.INFO, __file__, 1, "Task succeeded", (context,), None
    )
    assert CeleryTaskDiagnosticFilter().filter(record)
    assert "synthetic-private-result" not in str(record.__dict__)
    assert record.data["duration_seconds"] == 1.25
    assert record.data["error_type"] is None
    assert record.data["event"] == "task_succeeded"
    assert "failure" not in record.getMessage()


def test_unknown_provider_code_never_becomes_a_safe_diagnostic_identifier():
    private = "synthetic-private-token"
    diagnostic = task_failure_diagnostic(WhatsAppCloudApiError(private, code=private))
    assert diagnostic.code is None
    assert private not in str(diagnostic)
    assert diagnostic.exception_type == "WhatsAppCloudApiError"
