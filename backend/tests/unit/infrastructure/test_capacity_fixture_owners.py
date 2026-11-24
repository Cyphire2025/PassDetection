"""Exercise fixture imports and command dispatch without database/provider effects."""

from __future__ import annotations

import importlib
import json
import pickle
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints
from unittest.mock import AsyncMock, Mock

import pytest


def fixture(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[4] / "scripts/qa"))
    module = importlib.import_module("capacity_fixtures")
    monkeypatch.setattr(module, "isolated", Mock())
    monkeypatch.setattr(module, "engine", SimpleNamespace(dispose=AsyncMock()))
    for name in ("seed", "queue_retries", "observe", "verify"):
        monkeypatch.setattr(module, name, AsyncMock(return_value={"synthetic": True}))
    return module


def arguments(monkeypatch, action="observe", run_id="a" * 32, seconds="1"):
    monkeypatch.setattr("sys.argv", ["capacity_fixtures.py", action, run_id, "--seconds", seconds])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,function", [("seed", "seed"), ("queues", "queue_retries"), ("verify", "verify")]
)
async def test_original_action_dispatch_keeps_result_json_and_engine_disposal(
    monkeypatch, action, function
):
    module = fixture(monkeypatch)
    arguments(monkeypatch, action)
    printed = Mock()
    monkeypatch.setattr(module, "print", printed, raising=False)
    await module.main()
    module.isolated.assert_called_once_with()
    getattr(module, function).assert_awaited_once_with("a" * 32)
    module.engine.dispose.assert_awaited_once_with()
    assert json.loads(printed.call_args.args[0]) == {"synthetic": True}
    assert printed.call_args.kwargs == {"flush": True}


@pytest.mark.asyncio
async def test_observation_keeps_exact_duration_and_disposes_after_failure(monkeypatch):
    module = fixture(monkeypatch)
    arguments(monkeypatch, seconds="1800")
    module.observe.side_effect = RuntimeError("synthetic observation failure")
    with pytest.raises(RuntimeError, match="synthetic observation failure"):
        await module.main()
    module.observe.assert_awaited_once_with("a" * 32, 1800)
    module.engine.dispose.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "run_id,seconds",
    [
        ("a" * 31, "1"),
        ("a" * 33, "1"),
        ("A" * 32, "1"),
        ("../" + "a" * 29, "1"),
        ("a" * 32, "0"),
        ("a" * 32, "1801"),
    ],
)
async def test_invalid_run_scope_or_duration_fails_before_any_action(monkeypatch, run_id, seconds):
    module = fixture(monkeypatch)
    arguments(monkeypatch, run_id=run_id, seconds=seconds)
    with pytest.raises(RuntimeError, match="bounded synthetic run identifier/duration"):
        await module.main()
    for name in ("seed", "queue_retries", "observe", "verify"):
        getattr(module, name).assert_not_called()
    module.engine.dispose.assert_not_called()


@pytest.mark.asyncio
async def test_isolation_failure_precedes_argument_dispatch_and_side_effects(monkeypatch):
    module = fixture(monkeypatch)
    arguments(monkeypatch)
    module.isolated.side_effect = RuntimeError("synthetic isolation rejected")
    with pytest.raises(RuntimeError, match="synthetic isolation rejected"):
        await module.main()
    for name in ("seed", "queue_retries", "observe", "verify"):
        getattr(module, name).assert_not_called()


def test_public_functions_are_direct_aliases_with_legacy_pickle_and_hints(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[4] / "scripts/qa"))
    facade = importlib.import_module("capacity_fixtures")
    for module_name, names in (
        ("capacity_fixture_contract", ("identifier",)),
        ("capacity_fixture_seed", ("seed",)),
        ("capacity_fixture_jobs", ("queue_retries", "verify")),
        ("capacity_fixture_observer", ("observe",)),
        ("capacity_fixtures", ("main",)),
    ):
        owner = importlib.import_module(module_name)
        for name in names:
            function = getattr(owner, name)
            assert getattr(facade, name) is function
            assert pickle.loads(pickle.dumps(function)) is function
            assert get_type_hints(function)
