"""Patch shared dependencies across explicit imports in decomposed route tests.

Compatibility exports remain useful for asserting old import contracts. A mock
must, however, replace the reference where each focused router uses it. Keep
that test concern here rather than adding mutable production module proxies.
"""

from __future__ import annotations

import importlib
import sys
from contextlib import ExitStack, contextmanager
from types import ModuleType
from unittest.mock import patch

PREFIX = "app.presentation.api.v1.routes."
FACADES = (PREFIX + "whatsapp", PREFIX + "document_distribution")


def _consumers(module: ModuleType, name: str):
    original = getattr(module, name)
    yield module
    for module_name, candidate in tuple(sys.modules.items()):
        if (
            module_name.startswith(module.__name__ + "_")
            and candidate is not None
            and getattr(candidate, name, object()) is original
        ):
            yield candidate


def set_route_dependency(monkeypatch, target, *args, **kwargs):
    if isinstance(target, str):
        module_path, name = target.rsplit(".", 1)
        if module_path not in FACADES:
            return monkeypatch.setattr(target, *args, **kwargs)
        module = importlib.import_module(module_path)
        (value,) = args
    else:
        module = target
        name, value = args
    if not isinstance(module, ModuleType) or module.__name__ not in FACADES:
        return monkeypatch.setattr(target, *args, **kwargs)
    for consumer in tuple(_consumers(module, name)):
        monkeypatch.setattr(consumer, name, value, **kwargs)


@contextmanager
def patch_route_dependency(target: str, *args, **kwargs):
    module_path, name = target.rsplit(".", 1)
    if module_path not in FACADES:
        with patch(target, *args, **kwargs) as replacement:
            yield replacement
        return
    module = importlib.import_module(module_path)
    consumers = tuple(_consumers(module, name))
    with ExitStack() as stack:
        replacement = stack.enter_context(patch.object(consumers[0], name, *args, **kwargs))
        for consumer in consumers[1:]:
            stack.enter_context(patch.object(consumer, name, replacement))
        yield replacement
