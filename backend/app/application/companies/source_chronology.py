"""Signed continuation for original submission chronology, unknown dates last."""
from collections.abc import Sequence
from typing import Any

from sqlalchemy.engine import Row

from app.application.mcp.read_cursor import MCPReadCursor
from app.infrastructure.database.traveller_reuse_models import TravellerMatchCaseModel as MatchCase


def source_page_cursor(codec: MCPReadCursor, state: dict[str, Any],
    cases: Sequence[Row[tuple[MatchCase, str]]], more: bool,
) -> str | None:
    if not more or not cases:
        return None
    last = cases[-1][0]
    return codec.next({**state, "unknown_source_date": last.source_created_at is None},
        {"id": last.id, "created_at": last.source_created_at or last.created_at})
