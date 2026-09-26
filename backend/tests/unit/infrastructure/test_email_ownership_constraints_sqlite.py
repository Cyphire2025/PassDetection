"""Behavioral proof that the shared FK-enabled fixture rejects invalid scopes."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.email_ownership_constraints import CASES, assert_email_parent_constraint


@pytest.mark.parametrize("case", CASES)
async def test_email_parent_scope_is_enforced_by_sqlite(db_session: AsyncSession, case: str) -> None:
    assert await db_session.scalar(text("PRAGMA foreign_keys")) == 1
    await assert_email_parent_constraint(db_session, case)
