from __future__ import annotations

import io
import json
import logging
from types import SimpleNamespace

import pytest
import structlog

from app.core.logging import logger as application_logging


@pytest.fixture
def isolated_logging(monkeypatch):
    root = logging.getLogger()
    previous_handlers = root.handlers[:]
    previous_level = root.level
    previous_configuration = structlog.get_config()
    previous_levels = {
        name: value.level
        for name, value in logging.Logger.manager.loggerDict.items()
        if isinstance(value, logging.Logger)
    }
    for handler in previous_handlers:
        root.removeHandler(handler)
    output = io.StringIO()
    monkeypatch.setattr(application_logging, "sys", SimpleNamespace(stdout=output))
    settings = SimpleNamespace(is_production=True, app_debug=False)
    monkeypatch.setattr(application_logging, "get_settings", lambda: settings)
    try:
        yield root, output, settings
    finally:
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()
        for handler in previous_handlers:
            root.addHandler(handler)
        root.setLevel(previous_level)
        for name, level in previous_levels.items():
            logging.getLogger(name).setLevel(level)
        structlog.configure(**previous_configuration)


def test_repeated_application_setup_emits_once_and_preserves_external_handlers(
    isolated_logging,
):
    root, output, _ = isolated_logging
    existing_handler_count = len(root.handlers)
    external_output = io.StringIO()
    external_handler = logging.StreamHandler(external_output)
    root.addHandler(external_handler)

    # The integration suite constructs hundreds of apps in one process. Every
    # log must still do one formatter/write operation per intended destination.
    for _ in range(160):
        application_logging.configure_logging()
    application_logging.get_logger("logging_setup_regression").error(
        "readiness_probe_failed", error_type="TimeoutError"
    )

    records = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(records) == 1
    assert records[0]["event"] == "readiness_probe_failed"
    assert records[0]["error_type"] == "TimeoutError"
    assert external_handler in root.handlers
    assert len(external_output.getvalue().splitlines()) == 1
    assert len(root.handlers) == existing_handler_count + 2


def test_reconfiguration_updates_output_format_and_level_without_stale_writes(
    isolated_logging, monkeypatch,
):
    root, first_output, settings = isolated_logging
    existing_handler_count = len(root.handlers)
    settings.is_production = False
    settings.app_debug = True
    application_logging.configure_logging()
    application_logging.get_logger("logging_setup_format").debug("development_event")
    before = first_output.getvalue()
    assert "development_event" in before

    second_output = io.StringIO()
    monkeypatch.setattr(application_logging.sys, "stdout", second_output)
    settings.is_production = True
    settings.app_debug = False
    application_logging.configure_logging()
    application_logging.get_logger("logging_setup_format").info("production_event")

    assert first_output.getvalue() == before
    assert json.loads(second_output.getvalue())["event"] == "production_event"
    assert root.level == logging.INFO
    assert len(root.handlers) == existing_handler_count + 1
    assert not first_output.closed


def test_fallback_reconfiguration_preserves_external_handler(isolated_logging, monkeypatch):
    root, output, _ = isolated_logging
    existing_handler_count = len(root.handlers)
    external_handler = logging.NullHandler()
    root.addHandler(external_handler)
    monkeypatch.setattr(application_logging, "structlog", None)
    for _ in range(3):
        application_logging.configure_logging()
    application_logging.get_logger("logging_setup_fallback").info("fallback_event")
    assert output.getvalue().count("fallback_event") == 1
    assert external_handler in root.handlers
    assert len(root.handlers) == existing_handler_count + 2
