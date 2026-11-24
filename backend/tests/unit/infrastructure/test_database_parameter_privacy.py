from __future__ import annotations

import logging
import traceback

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.infrastructure.database.session import engine as runtime_engine


@pytest.mark.parametrize("echo", [False, True])
@pytest.mark.parametrize(
    "private_value",
    ["synthetic-passport-P1234567", "+919999990001", "synthetic-sensitive-bearer-token"],
)
async def test_real_constraint_errors_and_sql_logs_do_not_expose_bound_values(
    private_value: str,
    echo: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Exercise the actual runtime engine's disclosure policy without a database
    # service. SQLite's original constraint detail contains no private value;
    # this isolates the additional SQLAlchemy parameter/traceback disclosure.
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        hide_parameters=runtime_engine.sync_engine.hide_parameters,
        echo=echo,
    )
    try:
        with caplog.at_level(logging.INFO, logger="sqlalchemy.engine.Engine"):
            async with engine.begin() as connection:
                await connection.execute(
                    text("CREATE TABLE private_values (id INTEGER PRIMARY KEY, value TEXT)")
                )
                statement = text(
                    "INSERT INTO private_values (id, value) VALUES (:id, :private_value)"
                )
                await connection.execute(statement, {"id": 1, "private_value": private_value})
                with pytest.raises(IntegrityError) as error:
                    await connection.execute(statement, {"id": 1, "private_value": private_value})

        formatted = "".join(traceback.format_exception(error.value))
        assert "UNIQUE constraint failed" in str(error.value)
        assert "INSERT INTO private_values" in str(error.value)
        assert private_value not in str(error.value)
        assert private_value not in formatted
        assert private_value not in caplog.text
    finally:
        await engine.dispose()
