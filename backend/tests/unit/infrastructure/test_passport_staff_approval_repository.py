"""Persistence contract for staff-approval row serialization."""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.dialects import postgresql

from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)


class PassportStaffApprovalRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_staff_approval_read_uses_postgres_row_lock(self) -> None:
        submission_id = uuid.uuid4()
        model = object()
        entity = object()
        result = SimpleNamespace(scalar_one_or_none=lambda: model)
        session = SimpleNamespace(execute=AsyncMock(return_value=result))
        repository = PassportSubmissionRepository(session)  # type: ignore[arg-type]

        with patch.object(
            PassportSubmissionRepository,
            "_to_entity",
            return_value=entity,
        ):
            loaded = await repository.get_by_id_for_update(submission_id)

        self.assertIs(loaded, entity)
        statement = session.execute.await_args.args[0]
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("FOR UPDATE", sql)
        self.assertIn(str(submission_id), sql)


if __name__ == "__main__":
    unittest.main()
