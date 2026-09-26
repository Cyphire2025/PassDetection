import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.data_invariants import CASES, assert_data_invariant


@pytest.mark.parametrize("case", CASES)
async def test_tenant_and_ecr_constraints(db_session: AsyncSession, case: str) -> None:
    await assert_data_invariant(db_session, case)
