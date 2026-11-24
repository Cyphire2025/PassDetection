"""Typed dashboard MCP settings access shared by focused route owners."""

from __future__ import annotations

from typing import cast

from fastapi import Request

from app.core.config.settings import Settings


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


# Keep established facade import and serialized function identities.
for _function in (_settings,):
    _function.__module__ = "app.presentation.api.v1.routes.mcp_admin"
del _function
