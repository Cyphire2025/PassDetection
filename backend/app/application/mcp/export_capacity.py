"""Transport-neutral service boundary for shared MCP export admission."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from app.application.mcp.artifacts import ArtifactError
from app.core.mcp_export_admission import ExportAdmissionBusy, export_slot

_P = ParamSpec("_P")
_R = TypeVar("_R")


class ExportCapacityBusy(ArtifactError):
    def __init__(self) -> None:
        super().__init__("Export capacity is busy; retry or resume later", 503)


def admitted_export(function: Callable[_P, Awaitable[_R]]) -> Callable[_P, Awaitable[_R]]:
    @wraps(function)
    async def admitted(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        try:
            with export_slot():
                return await function(*args, **kwargs)
        except ExportAdmissionBusy as exc:
            raise ExportCapacityBusy() from exc

    return admitted
