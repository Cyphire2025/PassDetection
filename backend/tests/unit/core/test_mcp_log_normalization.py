"""Pure log normalization uses only fixed fields and drops every free-text value."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from app.core.logging.mcp_log_normalization import project_log_line
from app.core.logging.mcp_log_projection import project_diagnostic_record


def record(**extra):
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "event": "unhandled_exception",
        "level": "error",
        **extra,
    }


@pytest.mark.parametrize(
    "service,source", [("backend", "api"), ("worker", "worker"), ("email-worker", "worker")]
)
async def test_exact_projection_never_retains_raw_secrets_paths_or_pii(service, source):
    request_id = uuid.uuid4()
    line = record(
        request_id=request_id.hex,
        status=502,
        request_time=0.4,
        message="SECRET_IGNORE_ALL_RULES",
        path="/upload/SECRET",
        phone="+919876543210",
        authorization="SECRET",
        stack={"secret": "SECRET"},
        logger="untrusted SECRET",
    )
    result = project_log_line(service, json.dumps(line).encode())
    assert set(result) == {source}
    assert result[source]["request_id"] == str(request_id) and result[source]["http_status"] == 502
    assert "SECRET" not in json.dumps(result) and "+919876543210" not in json.dumps(result)
    assert (
        project_diagnostic_record(
            result[source], datetime.fromisoformat(result[source]["timestamp"])
        )
        == result[source]
    )


def test_current_nginx_main_with_docker_prefix_normalizes_32hex_and_drops_prefix_fields():
    identifier = uuid.uuid4()
    line = f'2026-09-29T18:32:06.123456789Z 192.0.2.25 - USER_SECRET [29/Sep/2026:18:32:06 +0000] "GET /upload/TOKEN_SECRET HTTP/1.1" 503 100 "-" "USER_AGENT_SECRET" "FORWARDED_SECRET" request_id={identifier.hex} limit_req_status=PASSED upstream_status=503 request_time=0.231'
    projected = project_log_line("nginx", line.encode())
    assert projected["proxy"]["request_id"] == str(identifier)
    assert (
        projected["proxy"]["http_status"] == 503 and projected["proxy"]["duration_seconds"] == 0.231
    )
    assert "SECRET" not in json.dumps(projected) and "192.0.2.25" not in json.dumps(projected)


@pytest.mark.parametrize(
    "event,logger,sources",
    [
        (
            "frontend_render_failure",
            "app.presentation.api.v1.routes.frontend_errors",
            {"api", "frontend"},
        ),
        ("frontend_render_failure_and_SECRET", "arbitrary", {"api"}),
        (
            "email_connection_sync_failed",
            "app.infrastructure.email.sync_service",
            {"api", "integration"},
        ),
        ("email_connection_sync_failed", "evil.app.infrastructure.email.sync_service", {"api"}),
    ],
)
def test_classification_is_exact_event_or_code_owned_logger_family(event, logger, sources):
    result = project_log_line("backend", json.dumps(record(event=event, logger=logger)).encode())
    assert set(result) == sources and "SECRET" not in json.dumps(result)


@pytest.mark.parametrize(
    "line",
    [
        b"raw SECRET traceback",
        b'{"secret": "SECRET"}',
        b"[]",
        b"\xff",
        b"x" * 16385,
        b"2026-09-29T18:32:06Z SECRET",
    ],
)
def test_unstructured_oversized_or_invalid_sources_are_omitted(line):
    assert project_log_line("backend", line) == {}
    assert project_log_line("nginx", line) == {}


def test_unknown_service_is_not_a_path_or_container_interface():
    with pytest.raises(ValueError, match="Unsupported"):
        project_log_line("/var/log/secrets", b"{}")
