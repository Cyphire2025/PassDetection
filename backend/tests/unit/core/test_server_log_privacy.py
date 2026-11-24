from __future__ import annotations

import builtins
import importlib.util
import io
import json
import logging
import sys
from pathlib import Path
from types import ModuleType

import pytest
import structlog
from sqlalchemy.exc import IntegrityError

from app.core.logging.server_diagnostics import (
    ServerExceptionDiagnosticFilter,
    install_server_diagnostic_filter,
)
from tests.unit.core.asgi_log_sink_control import configure_sink, exercise_cycle


@pytest.fixture(autouse=True)
def restore_logging_state():
    root = logging.getLogger()
    loggers = {
        "": root,
        **{
            name: logger
            for name, logger in logging.Logger.manager.loggerDict.items()
            if isinstance(logger, logging.Logger)
        },
    }
    saved = {
        name: (logger.handlers[:], logger.filters[:], logger.level, logger.propagate)
        for name, logger in loggers.items()
    }
    config = structlog.get_config()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    try:
        yield
    finally:
        for name, logger in {
            "": root,
            **{
                name: logger
                for name, logger in logging.Logger.manager.loggerDict.items()
                if isinstance(logger, logging.Logger)
            },
        }.items():
            handlers, filters, level, propagate = saved.get(name, ([], [], logging.NOTSET, True))
            for handler in logger.handlers:
                if handler not in handlers:
                    handler.close()
            logger.handlers, logger.filters = handlers, filters
            logger.setLevel(level)
            logger.propagate = propagate
        structlog.configure(**config)
        structlog.contextvars.clear_contextvars()


@pytest.mark.parametrize("protocol", ["h11", "httptools"])
@pytest.mark.parametrize("mode", ["application-root-json", "uvicorn-default-stderr"])
@pytest.mark.parametrize("kind", ["database-driver-shaped", "provider-shaped"])
async def test_actual_asgi_cycle_does_not_emit_private_exception_messages(
    monkeypatch,
    protocol: str,
    mode: str,
    kind: str,
) -> None:
    private = f"synthetic-{kind}-private-passport-P1234567"
    failure: Exception = (
        IntegrityError(
            "INSERT INTO synthetic_passports VALUES (:passport)",
            {"passport": private},
            RuntimeError(f"duplicate key passport=({private}) already exists"),
            hide_parameters=True,
        )
        if kind == "database-driver-shaped"
        else RuntimeError(f"Synthetic provider rejected {private}")
    )
    original_args = failure.args
    original_database = (
        (failure.orig, failure.params, failure.statement, failure.hide_parameters)
        if isinstance(failure, IntegrityError) else None
    )
    if isinstance(failure, IntegrityError):
        assert failure.hide_parameters
        assert "SQL parameters hidden" in str(failure)
        assert private in str(failure)  # Original driver text remains private too.
    application, server = configure_sink(monkeypatch, mode)
    wire = (await exercise_cycle(protocol, failure)).decode()
    logs = application.getvalue() + server.getvalue()
    own = [
        json.loads(line)
        for line in application.getvalue().splitlines()
        if line.startswith("{") and json.loads(line).get("event") == "unhandled_exception"
    ]
    assert len(own) == 1
    assert private not in json.dumps(own)
    assert "500 Internal Server Error" in wire and "INTERNAL_SERVER_ERROR" in wire
    assert private not in wire
    assert private not in logs
    assert "ASGI application failure:" in logs and "frames=" in logs
    assert type(failure).__name__ in logs
    assert own[0]["request_id"] in logs
    assert failure.args == original_args
    if isinstance(failure, IntegrityError):
        assert (failure.orig, failure.params, failure.statement, failure.hide_parameters) == original_database


def _chained_failure(depth: int) -> None:
    if depth:
        _chained_failure(depth - 1)
        return
    try:
        raise ValueError("synthetic-private-inner-passport")
    except ValueError as cause:
        raise RuntimeError("synthetic-private-outer-provider") from cause


@pytest.mark.parametrize("mode", ["application-root-json", "uvicorn-default-stderr"])
def test_projection_precedes_fanout_clears_cached_chains_and_retains_bounded_frames(
    monkeypatch,
    mode: str,
) -> None:
    application, server = configure_sink(monkeypatch, mode)
    logger = logging.getLogger("uvicorn.error")
    external = io.StringIO()
    external_handler = logging.StreamHandler(external)
    external_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(external_handler)
    try:
        _chained_failure(32)
    except RuntimeError as failure:
        original = (failure.args, failure.__traceback__, failure.__cause__, failure.__context__)
        cause_args = failure.__cause__.args
        record = logging.LogRecord(
            "uvicorn.error",
            logging.ERROR,
            __file__,
            1,
            "synthetic-private-message %s",
            ("synthetic-private-argument",),
            sys.exc_info(),
        )
        # Model an earlier formatter/factory's cached traceback and message.
        logging.Formatter().format(record)
        assert "synthetic-private-inner" in record.exc_text
        record.stack_info = "synthetic-private-stack"
        record.request_id = "b0c233d9-981e-43d0-bb04-c0ab378cf826"
        logger.handle(record)
        assert (
            failure.args,
            failure.__traceback__,
            failure.__cause__,
            failure.__context__,
        ) == original
        assert failure.__cause__.args == cause_args
    logs = application.getvalue() + server.getvalue() + external.getvalue()
    assert "synthetic-private" not in logs
    assert "RuntimeError" in logs
    assert record.request_id in logs
    assert 1 <= len(record.args["traceback"].splitlines()) <= 16
    assert all(frame.rsplit(":", 1)[1].isdigit() for frame in record.args["traceback"].splitlines())
    assert record.exc_info is None and record.exc_text is None and record.stack_info is None
    assert "synthetic-private" not in record.message
    assert external.getvalue()


def test_cached_text_without_exc_info_is_projected_without_reflecting_invalid_request_id(
    monkeypatch,
):
    application, _ = configure_sink(monkeypatch, "application-root-json")
    record = logging.LogRecord(
        "uvicorn.error", logging.ERROR, __file__, 1, "synthetic-private-message", (), None
    )
    record.exc_text = "synthetic-private-cached-chain"
    record.request_id = "synthetic-private-invalid-request-id"
    logging.getLogger("uvicorn.error").handle(record)
    assert "synthetic-private" not in application.getvalue()
    assert "request_id=unknown" in application.getvalue()
    assert record.exc_text is None


def test_ordinary_server_messages_levels_and_handlers_are_unchanged(monkeypatch):
    application, _ = configure_sink(monkeypatch, "application-root-json")
    logger = logging.getLogger("uvicorn.error")
    logger.setLevel(logging.WARNING)
    handlers = logger.handlers[:]
    for _ in range(160):
        install_server_diagnostic_filter()
    logger.warning("Worker operational control %s", "unchanged")
    assert "Worker operational control unchanged" in application.getvalue()
    assert logger.level == logging.WARNING and logger.handlers == handlers
    assert sum(isinstance(item, ServerExceptionDiagnosticFilter) for item in logger.filters) == 1


def test_projection_does_not_evaluate_exception_truthiness_and_supports_optional_structlog(
    monkeypatch,
):
    application, _ = configure_sink(monkeypatch, "application-root-json")
    importing = builtins.__import__

    def no_structlog(name, *args, **kwargs):
        if name == "structlog.contextvars":
            raise ModuleNotFoundError("synthetic optional dependency absent")
        return importing(name, *args, **kwargs)

    def invalid_truthiness(self):
        raise AssertionError("Exception truthiness must not be evaluated")

    error_type = type("SyntheticFalseError", (RuntimeError,), {"__bool__": invalid_truthiness})
    monkeypatch.setattr(builtins, "__import__", no_structlog)
    failure = error_type("synthetic-private-exception")
    record = logging.LogRecord(
        "uvicorn.error", logging.ERROR, __file__, 1, "failure", (), (type(failure), failure, None)
    )
    logging.getLogger("uvicorn.error").handle(record)
    assert "synthetic-private" not in application.getvalue()
    assert "SyntheticFalseError" in application.getvalue()


def test_production_worker_installs_projection_before_base_handler_replacement(monkeypatch):
    _, _ = configure_sink(monkeypatch, "application-root-json")
    logger = logging.getLogger("uvicorn.error")
    logger.filters = []
    output = io.StringIO()

    class SyntheticWorkerBase:
        CONFIG_KWARGS = {"loop": "auto", "http": "auto"}

        def __init__(self, *args, **kwargs):
            # The real UvicornWorker constructor replaces this same logger's
            # handlers with Gunicorn's; it does not replace its filters.
            assert any(isinstance(item, ServerExceptionDiagnosticFilter) for item in logger.filters)
            logger.handlers = [logging.StreamHandler(output)]
            logger.propagate = False
            try:
                raise RuntimeError("synthetic-private-worker-exception")
            except RuntimeError:
                logger.exception("worker startup control")

    module = ModuleType("uvicorn.workers")
    module.UvicornWorker = SyntheticWorkerBase
    monkeypatch.setitem(sys.modules, "uvicorn.workers", module)
    path = Path(__file__).parents[3] / "app/infrastructure/bounded_uvicorn_worker.py"
    spec = importlib.util.spec_from_file_location("synthetic_bounded_worker", path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    worker = loaded.BoundedUvicornWorker()
    assert worker.CONFIG_KWARGS["ws_max_size"] == 1024
    assert worker.CONFIG_KWARGS["ws_max_queue"] == 4
    assert worker.CONFIG_KWARGS["ws_per_message_deflate"] is False
    assert "synthetic-private" not in output.getvalue()
    assert "RuntimeError" in output.getvalue()
